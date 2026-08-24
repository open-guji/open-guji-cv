# -*- coding: utf-8 -*-
"""elastic 判据的刻度标定：把原始分搬回 coverage 的数值刻度上。

    PYTHONPATH=. python scripts/calibrate_elastic.py ../open-guji-dataset/char-clustering

**为什么要标定。** elastic（软覆盖 + 分块弹性对齐）改的是**排序**，但它的
数值分布与 coverage 不同（同字对原始分 ~0.90 而非 ~0.99）。而 COV_HIGH /
COV_LOW / MISS_WMAX、以及 seeding.py 的 MATCH_SOLO_COV=0.99、
MATCH_SOLO_OCR_COV=0.95 全是按 coverage 的分布标定的闸。直接换判据会把这
一串阈值的**操作点**一起挪走，两件事混在一次改动里就说不清是谁的功过。

**怎么标。** 在一个与生产同分布的对群上（char-clustering 冻结分片的
kNN top-k 对——正是库匹配与聚类真正会去验的那批对），把 elastic 原始分与
coverage 各自排序，逐分位对齐，得到单调分段线性映射 raw → cov 刻度。
于是：同一个分位 → 同一个数值 → **每个既有阈值放行的比例原样保留**，
变的只是**放行谁**。wmax 同理（12×12 窗口残差，方向也是越大越糟）。

产出的锚点表贴回 `verify.py` 的 `_CAL_*`；重标（改 tau/block/local 或换
对群）就是重跑本脚本、替换那四行。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from open_guji_cv.clustering.features import get_feature  # noqa: E402
from open_guji_cv.clustering.verify import (SCALES, MAX_SHIFT,  # noqa: E402
                                            ELASTIC_BLOCK, ELASTIC_LOCAL,
                                            ELASTIC_TAU, MISS_WIN,
                                            _elastic_align, _elastic_miss,
                                            _rescale, _shifted_view,
                                            verify_pair_cov)

# 分位点：上尾加密——阈值都住在那儿。
LEVELS = np.r_[np.linspace(0.0, 0.90, 19),
               [0.92, 0.94, 0.96, 0.97, 0.98, 0.99, 0.995, 0.998, 0.999, 1.0]]


def elastic_raw(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """未校准的 (覆盖率, 窗口残差)。"""
    size = a.shape[0]
    if int(a.sum()) == 0 or int(b.sum()) == 0:
        return 0.0, 0.0
    raw, (dx, dy), scale = _elastic_align(a, b, MAX_SHIFT, SCALES,
                                          ELASTIC_TAU, ELASTIC_BLOCK,
                                          ELASTIC_LOCAL)
    padded = np.zeros((size + 2 * MAX_SHIFT, size + 2 * MAX_SHIFT), dtype=np.uint8)
    padded[MAX_SHIFT:MAX_SHIFT + size, MAX_SHIFT:MAX_SHIFT + size] = _rescale(b, scale)
    b_aligned = _shifted_view(padded, dx, dy, size, MAX_SHIFT)
    miss_a, miss_b = _elastic_miss(a, b_aligned, ELASTIC_TAU, ELASTIC_BLOCK,
                                   ELASTIC_LOCAL)
    k = (MISS_WIN, MISS_WIN)
    w = max(float(cv2.boxFilter(miss_a, -1, k, normalize=False).max()),
            float(cv2.boxFilter(miss_b, -1, k, normalize=False).max()))
    return raw, w


def load_patches(shard_dir: Path) -> np.ndarray:
    data = json.loads((shard_dir / "expected.json").read_text(encoding="utf-8"))
    out = []
    for inst in data["instances"]:
        img = cv2.imread(str(shard_dir / inst["crop"]), cv2.IMREAD_GRAYSCALE)
        out.append((img > 127).astype(np.uint8))
    return np.asarray(out)


def knn_pairs(patches: np.ndarray, k: int, backend: str) -> list[tuple[int, int]]:
    feats = get_feature(backend).extract(patches)
    sims = feats @ feats.T
    np.fill_diagonal(sims, -np.inf)
    pairs = set()
    for i in range(len(patches)):
        for j in np.argsort(-sims[i])[:k]:
            pairs.add((min(i, int(j)), max(i, int(j))))
    return sorted(pairs)


def monotone_anchors(src: np.ndarray, dst: np.ndarray,
                     end: tuple[float, float]) -> tuple[list, list]:
    """逐分位配对 → 严格递增的插值锚点。

    两侧都必须严格递增：src 并列会让 np.interp 的取值无定义，**dst 并列**
    则更糟——coverage 的上尾整片压在 1.0，照抄过来会把 elastic 在高分区的
    排序全抹平（而那正是本次要改善的区间）。所以只留双侧严格递增的分位，
    再接上端点 `end`，让剩下的高分区线性铺满、保序。
    """
    xs = np.quantile(src, LEVELS)
    ys = np.quantile(dst, LEVELS)
    ax, ay = [0.0], [0.0]     # 原点：低分区也保序，别在夹断处并列
    for x, y in zip(xs, ys):
        if ax and (x <= ax[-1] or y <= ay[-1]):
            continue
        if y >= end[1]:      # 到顶就停，剩下的交给端点线性铺满
            break
        ax.append(round(float(x), 4))
        ay.append(round(float(y), 4))
    if ax and end[0] > ax[-1] and end[1] > ay[-1]:
        ax.append(round(float(end[0]), 4))
        ay.append(round(float(end[1]), 4))
    return ax, ay


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", help="char-clustering 数据集目录")
    ap.add_argument("--shards", nargs="*",
                    default=["001-vol01-body", "002-vol02-body"])
    ap.add_argument("--k", type=int, default=10, help="每实例取几个近邻成对")
    ap.add_argument("--feature", default="hog")
    ap.add_argument("--dump", default=None, help="把逐对原始分存成 npz（重拟合用）")
    ap.add_argument("--from-dump", default=None, help="跳过计算，直接用 npz 重拟合")
    args = ap.parse_args()

    if args.from_dump:
        z = np.load(args.from_dump)
        raws, ws, covs, wmaxs = z["raw"], z["wraw"], z["cov"], z["wmax"]
        _emit(raws, ws, covs, wmaxs, args)
        return

    raws, ws, covs, wmaxs = [], [], [], []
    for name in args.shards:
        shard = Path(args.dataset) / "samples" / name
        patches = load_patches(shard)
        pairs = knn_pairs(patches, args.k, args.feature)
        print(f"[{name}] {len(patches)} 实例 / {len(pairs)} 对", flush=True)
        for n, (i, j) in enumerate(pairs):
            a, b = patches[i], patches[j]
            r, w = elastic_raw(a, b)
            v = verify_pair_cov(a, b)
            raws.append(r); ws.append(w)
            covs.append(v.f1); wmaxs.append(v.diff_blob_ratio)
            if n % 5000 == 0:
                print(f"  {n}/{len(pairs)}", flush=True)

    _emit(np.asarray(raws), np.asarray(ws), np.asarray(covs),
          np.asarray(wmaxs), args)


def _emit(raws, ws, covs, wmaxs, args) -> None:
    cr, cc = monotone_anchors(raws, covs, end=(1.0, 1.0))
    wr, ww = monotone_anchors(ws, wmaxs, end=(float(ws.max()) * 1.5,
                                              float(wmaxs.max()) * 1.5))
    if args.dump:
        np.savez_compressed(args.dump, raw=raws, cov=covs, wraw=ws, wmax=wmaxs)
        print(f"→ 原始配对已存 {args.dump}")
    print("\n把下面四行贴回 open_guji_cv/clustering/verify.py：\n")
    print(f"_CAL_RAW: tuple[float, ...] = {tuple(cr)}")
    print(f"_CAL_COV: tuple[float, ...] = {tuple(cc)}")
    print(f"_CAL_WRAW: tuple[float, ...] = {tuple(wr)}")
    print(f"_CAL_WMAX: tuple[float, ...] = {tuple(ww)}")
    print(f"\n对数 {len(raws)}；raw 分位 "
          f"{np.quantile(raws, [0.5, 0.9, 0.99, 0.999]).round(4).tolist()}；"
          f"cov 分位 {np.quantile(covs, [0.5, 0.9, 0.99, 0.999]).round(4).tolist()}")


if __name__ == "__main__":
    main()
