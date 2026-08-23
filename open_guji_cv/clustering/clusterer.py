"""M3 保守聚类：分块(blocking) → kNN 近邻图 → 配准验证 → 全连接校验合并。

保守性来源（设计文档 6.4）：
- 只有 verify_pair 判 same 的边才可能触发合并；
- 合并前跨簇抽查（complete-linkage 语义），防止链式传递污染（A~B, B~C 但 A≁C）；
- 特征/分块只负责"少算"，不负责"判同"。

纯函数核心 cluster()；IO 壳 run_book() 读 phase4_chars/ 写 phase5_clusters/。
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..utils.image_io import imread, imwrite
from .extractor import CharInstance, load_index
from .features import DEFAULT_FEATURE, get_feature
from .normalize import NORM_SIZE, normalize_patch
from .verify import (COV_HIGH, COV_LOW, DIFF_BLOB_RATIO, MISS_WMAX,
                     THETA_HIGH, THETA_LOW, verify_pair, verify_pair_cov)

KNN_K = 10
CROSS_CHECK_K = 3
N_REPS = 5
HW_BUCKET = 0.25       # h/w 比分桶宽度
INK_BUCKET = 0.08      # ink_ratio 分桶宽度


@dataclass
class ClusterParams:
    feature: str = DEFAULT_FEATURE
    # coverage（默认）：有界位移覆盖率判据，操作点见 verify.py 与
    # g3g4_error_analysis.md。overlap：旧配准 F1 判据，保留作对照。
    verify_method: str = "coverage"
    cov_high: float = COV_HIGH
    cov_low: float = COV_LOW
    miss_wmax: float = MISS_WMAX
    theta_high: float = THETA_HIGH
    theta_low: float = THETA_LOW
    diff_blob_ratio: float = DIFF_BLOB_RATIO
    knn_k: int = KNN_K
    cross_check_k: int = CROSS_CHECK_K
    n_reps: int = N_REPS
    seed: int = 7

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Cluster:
    cluster_id: str
    members: list[int]                      # patches 数组中的下标
    reps: list[int] = field(default_factory=list)
    cohesion: float = 0.0                   # 簇内验证边的平均 f1
    unsure_neighbors: list[str] = field(default_factory=list)


@dataclass
class ClusterResult:
    clusters: list[Cluster]
    params: ClusterParams
    n_instances: int
    n_verify_calls: int

    @property
    def stats(self) -> dict:
        sizes = [len(c.members) for c in self.clusters]
        return {
            "n_instances": self.n_instances,
            "n_clusters": len(self.clusters),
            "singleton_ratio": round(
                sum(1 for s in sizes if s == 1) / max(1, len(sizes)), 4),
            "max_cluster_size": max(sizes) if sizes else 0,
            "n_verify_calls": self.n_verify_calls,
        }


def has_through_vline(patch: np.ndarray, min_h: float = 0.7,
                      max_w: float = 0.15) -> bool:
    """归一图块内是否有"独立窄高组件"（高 ≥ min_h×S 且宽 ≤ max_w×S）。

    界行/边框被裹进图块时表现为与字形分离的细长竖条；
    "中/串"类字的通高竖笔与主体连通，组件宽度大，不会误伤。
    命中 → 列边界错位嫌疑，隔离出合并流程。"""
    import cv2
    s = patch.shape[0]
    n, _, stats, _ = cv2.connectedComponentsWithStats(patch, connectivity=8)
    for i in range(1, n):
        _, _, bw, bh, _ = stats[i]
        if bh >= min_h * s and bw <= max_w * s:
            return True
    return False


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


class ConservativeClusterer:
    """保守聚类器。patches: (N, S, S) uint8 {0,1} 归一二值图。"""

    def __init__(self, params: ClusterParams | None = None):
        self.params = params or ClusterParams()

    # ── 纯函数核心 ────────────────────────────────────────

    def cluster(self, patches: np.ndarray, feats: np.ndarray,
                hw_ratio: np.ndarray, ink_ratio: np.ndarray,
                quarantine: np.ndarray | None = None) -> ClusterResult:
        """quarantine[i]=True 的图块被隔离：不建候选边、强制单例。

        典型来源：图块内有贯穿竖线（列边界错位把界行裹进图块）——
        字被线切残后残形趋同，不同字可能互聚，必须排除出合并流程，
        以单例流向审查队列。"""
        p = self.params
        n = len(patches)
        rng = random.Random(p.seed)

        # 1. 粗分块（相邻桶也纳入候选，减少分块造成的碎片）
        buckets: dict[tuple[int, int], list[int]] = {}
        keys = np.stack([
            np.floor(hw_ratio / HW_BUCKET).astype(int),
            np.floor(ink_ratio / INK_BUCKET).astype(int),
        ], axis=1)
        for i, key in enumerate(map(tuple, keys)):
            if quarantine is not None and quarantine[i]:
                continue
            buckets.setdefault(key, []).append(i)

        # 2. 块内 kNN（含相邻桶）建候选边
        candidate_pairs: set[tuple[int, int]] = set()
        for (kh, ki), members in buckets.items():
            pool: list[int] = []
            for dh in (-1, 0, 1):
                for di in (-1, 0, 1):
                    pool.extend(buckets.get((kh + dh, ki + di), []))
            if len(pool) < 2:
                continue
            pool_arr = np.asarray(sorted(set(pool)))
            sims = feats[np.asarray(members)] @ feats[pool_arr].T  # 余弦相似
            k = min(p.knn_k + 1, len(pool_arr))
            for row, i in enumerate(members):
                top = np.argpartition(-sims[row], k - 1)[:k]
                for j in pool_arr[top]:
                    if i != j:
                        candidate_pairs.add((min(i, int(j)), max(i, int(j))))

        # 3. 配准验证候选边
        verdict_cache: dict[tuple[int, int], object] = {}

        def _verify(i: int, j: int):
            key = (min(i, j), max(i, j))
            if key not in verdict_cache:
                if p.verify_method == "coverage":
                    verdict_cache[key] = verify_pair_cov(
                        patches[key[0]], patches[key[1]],
                        cov_high=p.cov_high, cov_low=p.cov_low,
                        miss_wmax=p.miss_wmax)
                else:
                    verdict_cache[key] = verify_pair(
                        patches[key[0]], patches[key[1]],
                        theta_high=p.theta_high, theta_low=p.theta_low,
                        diff_blob_ratio=p.diff_blob_ratio)
            return verdict_cache[key]

        same_edges: list[tuple[float, int, int]] = []
        unsure_pairs: list[tuple[int, int]] = []
        for i, j in candidate_pairs:
            v = _verify(i, j)
            if v.verdict == "same":
                same_edges.append((v.f1, i, j))
            elif v.verdict == "unsure":
                unsure_pairs.append((i, j))

        # 4. 按分数降序合并 + 跨簇全连接抽查
        uf = _UnionFind(n)
        members_of: dict[int, list[int]] = {i: [i] for i in range(n)}
        edge_scores: dict[int, list[float]] = {i: [] for i in range(n)}
        same_edges.sort(reverse=True)
        for f1, i, j in same_edges:
            ri, rj = uf.find(i), uf.find(j)
            if ri == rj:
                edge_scores[ri].append(f1)
                continue
            ma, mb = members_of[ri], members_of[rj]
            ok = True
            for _ in range(min(p.cross_check_k, len(ma) * len(mb))):
                a = rng.choice(ma)
                b = rng.choice(mb)
                if _verify(a, b).verdict != "same":
                    ok = False
                    break
            if not ok:
                continue
            uf.union(ri, rj)
            root = uf.find(ri)
            merged = ma + mb
            scores = edge_scores[ri] + edge_scores[rj] + [f1]
            members_of.pop(ri, None)
            members_of.pop(rj, None)
            edge_scores.pop(ri, None)
            edge_scores.pop(rj, None)
            members_of[root] = merged
            edge_scores[root] = scores

        # 5. 组装结果 + unsure 邻接（潜在应并簇，供审查）
        roots = sorted(members_of, key=lambda r: -len(members_of[r]))
        cluster_of: dict[int, str] = {}
        clusters: list[Cluster] = []
        for rank, root in enumerate(roots):
            cid = f"c{rank:05d}"
            mem = sorted(members_of[root])
            scores = edge_scores[root]
            c = Cluster(cluster_id=cid, members=mem,
                        cohesion=round(float(np.mean(scores)), 4) if scores else 1.0)
            c.reps = self._pick_reps(mem, feats, rng)
            clusters.append(c)
            for m in mem:
                cluster_of[m] = cid

        neighbor_sets: dict[str, set[str]] = {c.cluster_id: set() for c in clusters}
        for i, j in unsure_pairs:
            ci, cj = cluster_of[i], cluster_of[j]
            if ci != cj:
                neighbor_sets[ci].add(cj)
                neighbor_sets[cj].add(ci)
        for c in clusters:
            c.unsure_neighbors = sorted(neighbor_sets[c.cluster_id])

        return ClusterResult(clusters=clusters, params=p,
                             n_instances=n, n_verify_calls=len(verdict_cache))

    def _pick_reps(self, members: list[int], feats: np.ndarray,
                   rng: random.Random) -> list[int]:
        """代表样本：特征 medoid + 离 medoid 最远者 + 随机补齐。"""
        if len(members) <= self.params.n_reps:
            return list(members)
        sub = feats[np.asarray(members)]
        sims = sub @ sub.T
        medoid_pos = int(np.argmax(sims.sum(axis=1)))
        far_pos = int(np.argmin(sims[medoid_pos]))
        reps = [members[medoid_pos], members[far_pos]]
        rest = [m for m in members if m not in reps]
        rng.shuffle(rest)
        reps.extend(rest[:self.params.n_reps - len(reps)])
        return sorted(set(reps), key=reps.index)

    # ── IO 壳 ────────────────────────────────────────────

    def run_book(self, book_out_dir: Path, montage: bool = True) -> dict:
        """读 phase4_chars/ → 归一化 + 特征 → 聚类 → 写 phase5_clusters/。"""
        book_out_dir = Path(book_out_dir)
        phase4 = book_out_dir / "phase4_chars"
        instances = load_index(phase4)
        if not instances:
            raise FileNotFoundError(f"phase4_chars 为空: {phase4}")

        print(f"归一化 {len(instances)} 个图块 ...")
        patches = np.zeros((len(instances), NORM_SIZE, NORM_SIZE), dtype=np.uint8)
        hw = np.ones(len(instances), dtype=np.float64)
        ink = np.zeros(len(instances), dtype=np.float64)
        for i, inst in enumerate(instances):
            img = imread(str(phase4 / inst.patch_path))
            if img is None:
                continue
            patches[i] = normalize_patch(img)
            hw[i] = inst.height / max(inst.width, 1e-6)
            ink[i] = inst.ink_ratio

        print(f"提取特征（{self.params.feature}）...")
        feats = get_feature(self.params.feature).extract(patches)

        quarantine = np.array([has_through_vline(p) for p in patches])
        n_q = int(quarantine.sum())
        if n_q:
            print(f"隔离含贯穿竖线的图块 {n_q} 个（列边界错位嫌疑，强制单例）")

        print("聚类 ...")
        result = self.cluster(patches, feats, hw, ink, quarantine=quarantine)

        out_dir = book_out_dir / "phase5_clusters"
        out_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(out_dir / "features.npz",
                            patches=patches, feats=feats)
        payload = {
            "params": result.params.to_dict(),
            "stats": result.stats,
            "clusters": [
                {"cluster_id": c.cluster_id,
                 "size": len(c.members),
                 "members": [instances[m].id for m in c.members],
                 "reps": [instances[m].id for m in c.reps],
                 "cohesion": c.cohesion,
                 "unsure_neighbors": c.unsure_neighbors}
                for c in result.clusters
            ],
        }
        with open(out_dir / "clusters.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        if montage:
            self._write_montages(out_dir / "montage", result, patches)

        with open(out_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump({"params": result.params.to_dict(),
                       "stats": result.stats}, f, ensure_ascii=False, indent=2)
        print(f"聚类完成: {result.stats}")
        return payload

    @staticmethod
    def _write_montages(montage_dir: Path, result: ClusterResult,
                        patches: np.ndarray, max_tiles: int = 100,
                        cols: int = 10) -> None:
        """每簇一张蒙太奇图（最多 max_tiles 个成员）。"""
        montage_dir.mkdir(parents=True, exist_ok=True)
        s = patches.shape[1]
        for c in result.clusters:
            if len(c.members) < 2:      # 单例簇不出图，减少文件数
                continue
            tiles = c.members[:max_tiles]
            rows = (len(tiles) + cols - 1) // cols
            canvas = np.full((rows * s, cols * s), 255, dtype=np.uint8)
            for t, m in enumerate(tiles):
                r, col_ = divmod(t, cols)
                canvas[r * s:(r + 1) * s, col_ * s:(col_ + 1) * s] = \
                    255 - patches[m] * 255
            imwrite(str(montage_dir / f"{c.cluster_id}.png"), canvas)
