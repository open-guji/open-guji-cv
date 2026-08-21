"""M7 反馈更新：标签事件流重放 + 阈值标定 + 字形库入库 + 用字习惯统计。

labels.jsonl（只追加）是唯一真源，当前标注状态 = 重放事件流。
事件类型：confirm / relabel / split / merge / mark / flag（见设计文档 9.3）。
flag 为簇级问题标记：impure（不同字混簇）/ truncated（截断不完整）/
contaminated（边框或邻字混入）/ not_text（非文字）。

run_update() 是 CLI `update` 命令的实现：消费标签，更新四类下游资产
（字形库 / 聚类阈值 / variant_prefs / 确认语料），全部显式批处理。
"""

from __future__ import annotations

import itertools
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class LabelState:
    """事件流重放后的标注状态。"""
    # cluster_id -> 确认标签（精确字形）
    cluster_labels: dict[str, str] = field(default_factory=dict)
    # instance_id -> 改判标签（优先级高于所属簇标签）
    instance_labels: dict[str, str] = field(default_factory=dict)
    # cluster_id -> 被移出的成员（split）
    removed: dict[str, set[str]] = field(default_factory=dict)
    # 合并组：cluster_id -> 代表簇 id
    merged_into: dict[str, str] = field(default_factory=dict)
    # instance_id -> 标记（damaged / empty / illegible / uncertain）
    marks: dict[str, str] = field(default_factory=dict)
    # cluster_id -> 簇级问题标记（impure 不同字混簇 / truncated 截断 /
    # contaminated 边框或邻字混入 / not_text 非文字）
    cluster_flags: dict[str, str] = field(default_factory=dict)
    # 人工发现的异类对（split 产生），用于阈值标定与回归集
    diff_pairs: list[tuple[str, str]] = field(default_factory=list)

    def label_of(self, instance_id: str, cluster_id: str | None) -> str | None:
        if instance_id in self.instance_labels:
            return self.instance_labels[instance_id]
        if cluster_id is None:
            return None
        if instance_id in self.removed.get(cluster_id, set()):
            return None
        root = self.merged_into.get(cluster_id, cluster_id)
        return self.cluster_labels.get(root)


def replay_events(events: list[dict]) -> LabelState:
    """重放事件流（纯函数）。后发事件覆盖先发事件。"""
    state = LabelState()
    for ev in events:
        op = ev.get("op")
        if op == "confirm":
            root = state.merged_into.get(ev["cluster"], ev["cluster"])
            state.cluster_labels[root] = ev["char"]
        elif op == "relabel":
            state.instance_labels[ev["instance"]] = ev["char"]
        elif op == "split":
            cluster = ev["cluster"]
            moved = set(ev.get("moved", []))
            state.removed.setdefault(cluster, set()).update(moved)
            # 移出成员与留守成员构成异类对（取首个留守成员配对即可）
            for m in moved:
                state.diff_pairs.append((cluster, m))
        elif op == "merge":
            ids = ev["clusters"]
            root = state.merged_into.get(ids[0], ids[0])
            for cid in ids[1:]:
                state.merged_into[cid] = root
                # 被并簇若已有标签，以代表簇为准；代表簇无标签则继承
                if root not in state.cluster_labels and cid in state.cluster_labels:
                    state.cluster_labels[root] = state.cluster_labels.pop(cid)
                state.cluster_labels.pop(cid, None)
        elif op == "mark":
            state.marks[ev["instance"]] = ev["flag"]
        elif op == "flag":
            if ev["flag"] == "clear":
                state.cluster_flags.pop(ev["cluster"], None)
            else:
                state.cluster_flags[ev["cluster"]] = ev["flag"]
    return state


def remap_events(events: list[dict],
                 cluster_of: dict[str, str]) -> tuple[list[dict], int]:
    """把事件里的簇 id 重绑到当前聚类。

    簇 id 由聚类过程生成，重跑聚类（改阈值、修切分）后会整体变号，
    而实例 id（book:page:col:idx）永久稳定。因此簇级事件写入时会带上
    当时的成员实例列表，这里按成员在当前聚类中的归属投票取多数簇。

    Args:
        cluster_of: instance_id → cluster_id（当前聚类）。

    Returns:
        (重绑后的事件流, 被重绑的事件数)。成员信息缺失或全部成员都已
        不在当前聚类中的事件原样保留（由调用方的校验决定其去留）。
    """
    out: list[dict] = []
    n_remapped = 0
    for ev in events:
        cid = ev.get("cluster")
        members = ev.get("members")
        if not cid or not members:
            out.append(ev)
            continue
        votes: dict[str, int] = {}
        for m in members:
            new = cluster_of.get(m)
            if new:
                votes[new] = votes.get(new, 0) + 1
        if not votes:
            out.append(ev)
            continue
        best = max(votes, key=lambda k: (votes[k], k))
        if best != cid:
            ev = {**ev, "cluster": best, "remapped_from": cid}
            n_remapped += 1
        out.append(ev)
    return out, n_remapped


def load_events(labels_path: Path) -> list[dict]:
    path = Path(labels_path)
    if not path.exists():
        return []
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def append_event(labels_path: Path, event: dict) -> None:
    path = Path(labels_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# ── 阈值标定 ──────────────────────────────────────────────

def calibrate_threshold(same_scores: np.ndarray, diff_scores: np.ndarray,
                        max_impurity: float = 0.001,
                        grid: int = 200) -> dict:
    """在人工标注的 same/diff 对分数分布上选 theta_high。

    theta = 满足 P(diff | score >= theta) <= max_impurity 的最小值
    （即该阈值以上的对中，异类对占比不超过 max_impurity）。

    Returns:
        {"theta_high": float, "same_recall": float, "impurity": float,
         "n_same": int, "n_diff": int}
    """
    same_scores = np.asarray(same_scores, dtype=np.float64)
    diff_scores = np.asarray(diff_scores, dtype=np.float64)
    if len(same_scores) == 0:
        raise ValueError("缺少 same 对样本，无法标定")

    best = None
    for theta in np.linspace(0.0, 1.0, grid + 1):
        n_same = int(np.count_nonzero(same_scores >= theta))
        n_diff = int(np.count_nonzero(diff_scores >= theta))
        accepted = n_same + n_diff
        if accepted == 0:
            continue
        impurity = n_diff / accepted
        if impurity <= max_impurity:
            best = {"theta_high": round(float(theta), 4),
                    "same_recall": round(n_same / len(same_scores), 4),
                    "impurity": round(impurity, 6),
                    "n_same": len(same_scores), "n_diff": len(diff_scores)}
            break
    if best is None:
        # 任何阈值都无法满足纯度约束 → 取 1.0（拒绝一切合并），交人工处理
        best = {"theta_high": 1.0, "same_recall": 0.0, "impurity": 0.0,
                "n_same": len(same_scores), "n_diff": len(diff_scores)}
    return best


# ── update 批处理（CLI `update` 命令的实现）───────────────

def derive_truth(state: LabelState, cluster_members: dict[str, list[str]]
                 ) -> dict[str, str]:
    """标注状态 → instance_id → 精确字形 真值表。"""
    truth: dict[str, str] = {}
    for cid, members in cluster_members.items():
        for iid in members:
            label = state.label_of(iid, cid)
            if label:
                truth[iid] = label
    truth.update(state.instance_labels)
    return truth


def _sample_pairs(groups: list[list[int]], max_pairs: int,
                  rng: random.Random) -> list[tuple[int, int]]:
    """从若干同组下标列表中抽样组内对。"""
    pairs: list[tuple[int, int]] = []
    for g in groups:
        pairs.extend(itertools.combinations(g, 2))
    rng.shuffle(pairs)
    return pairs[:max_pairs]


def run_update(book_out_dir: str | Path, glyph_store_dir: str | Path,
               edition_tag: str | None = None,
               calibrate: bool = True, max_pairs: int = 300,
               seed: int = 7) -> dict:
    """消费 labels.jsonl，更新字形库 / 阈值 / variant_prefs / 确认语料。"""
    from .extractor import load_index
    from .glyph_library import GlyphLibrary
    from .ids import parse_id, reading_order_key
    from .variants import VariantMap
    from .verify import verify_pair

    book_dir = Path(book_out_dir)
    book = book_dir.name
    edition = edition_tag or book
    store_dir = Path(glyph_store_dir)
    rng = random.Random(seed)
    variant_map = VariantMap.load()

    events = load_events(book_dir / "phase7_review" / "labels.jsonl")
    if not events:
        raise FileNotFoundError(
            f"没有标签事件: {book_dir / 'phase7_review' / 'labels.jsonl'}"
            "（请先运行 review 完成一轮审查）")
    instances = load_index(book_dir / "phase4_chars")
    pos_of = {inst.id: k for k, inst in enumerate(instances)}
    with open(book_dir / "phase5_clusters" / "clusters.json",
              encoding="utf-8") as f:
        clusters = json.load(f)["clusters"]
    cluster_members = {c["cluster_id"]: c["members"] for c in clusters}
    reps_of = {c["cluster_id"]: c["reps"] for c in clusters}

    # 簇 id 随重跑聚类变号 → 先按事件记录的成员实例重绑（见 remap_events）
    cluster_of = {m: cid for cid, ms in cluster_members.items() for m in ms}
    events, n_remapped = remap_events(events, cluster_of)
    state = replay_events(events)

    npz = np.load(book_dir / "phase5_clusters" / "features.npz")
    patches = npz["patches"]

    truth = derive_truth(state, cluster_members)
    summary: dict = {"events": len(events), "labeled_instances": len(truth),
                     "remapped_events": n_remapped}

    # 1) 字形库入库：每个已确认簇 root 取 medoid 图块
    lib = GlyphLibrary(store_dir)
    added = skipped = 0
    for cid, members in cluster_members.items():
        root = state.merged_into.get(cid, cid)
        char = state.cluster_labels.get(root)
        if not char:
            continue
        valid = [m for m in members
                 if state.label_of(m, cid) == char and m in pos_of]
        if not valid:
            continue
        medoid_id = next((r for r in reps_of.get(cid, []) if r in valid),
                         valid[0])
        patch = patches[pos_of[medoid_id]]
        # 去重：库中已有同字同版且配准判 same 的条目则跳过
        dup = any(h.verdict == "same" and h.char == char
                  for h in lib.query(patch, edition_hint=edition, k=3))
        if dup:
            skipped += 1
            continue
        lib.add(char, variant_map.semantic(char), patch,
                book=book, edition_tag=edition,
                n_confirmed=len(valid), source_instances=valid)
        added += 1
    lib.save()
    summary["glyphs_added"] = added
    summary["glyphs_skipped_dup"] = skipped

    # 2) 阈值标定：same 对来自同标签簇内，diff 对来自异标签簇间 + split 对
    if calibrate:
        by_char: dict[str, list[int]] = {}
        for iid, char in truth.items():
            if iid in pos_of:
                by_char.setdefault(char, []).append(pos_of[iid])
        same_pairs = _sample_pairs(list(by_char.values()), max_pairs, rng)

        diff_pairs: list[tuple[int, int]] = []
        chars = list(by_char)
        for a_i in range(len(chars)):
            for b_i in range(a_i + 1, len(chars)):
                a = rng.choice(by_char[chars[a_i]])
                b = rng.choice(by_char[chars[b_i]])
                diff_pairs.append((a, b))
        # split 产生的异类对（移出成员 vs 原簇 medoid）——最有价值的难例
        for cid, moved_id in state.diff_pairs:
            root = state.merged_into.get(cid, cid)
            reps = [r for r in reps_of.get(cid, []) if r in pos_of]
            if reps and moved_id in pos_of:
                diff_pairs.append((pos_of[reps[0]], pos_of[moved_id]))
        # impure 标记（人工判定「不同字混进同簇」）——同样是难负样本，
        # 且比 split 更省事：用户点一下即可。簇内两两皆为异类对。
        # 缺了它，diff 对全是随机易分对（f1 很低），标定出的阈值会
        # 荒谬地偏低（实测 0.565，而真实混簇的 f1 在 0.73 附近）。
        hard_diff: list[tuple[int, int]] = []
        for cid, flag in state.cluster_flags.items():
            if flag != "impure":
                continue
            ms = [m for m in cluster_members.get(cid, []) if m in pos_of]
            for a_i in range(len(ms)):
                for b_i in range(a_i + 1, len(ms)):
                    hard_diff.append((pos_of[ms[a_i]], pos_of[ms[b_i]]))
        rng.shuffle(diff_pairs)
        # 难例不参与截断采样：数量少且信息量最高，必须全部进入标定
        diff_pairs = hard_diff + diff_pairs[:max(0, max_pairs - len(hard_diff))]
        summary["hard_diff_pairs"] = len(hard_diff)

        if same_pairs and diff_pairs:
            same_scores = np.array([verify_pair(patches[a], patches[b]).f1
                                    for a, b in same_pairs])
            diff_scores = np.array([verify_pair(patches[a], patches[b]).f1
                                    for a, b in diff_pairs])
            calib = calibrate_threshold(same_scores, diff_scores)
            calib["book"] = book
            calib["n_same_pairs"] = len(same_pairs)
            calib["n_diff_pairs"] = len(diff_pairs)
            calib_dir = store_dir / "calib"
            calib_dir.mkdir(parents=True, exist_ok=True)
            with open(calib_dir / "thresholds.json", "w",
                      encoding="utf-8") as f:
                json.dump(calib, f, ensure_ascii=False, indent=2)
            summary["calibration"] = calib
        else:
            summary["calibration"] = "样本不足，跳过"

    # 3) variant_prefs：本书的异体字用字习惯（语义字 → 实际用形分布）
    prefs: dict[str, dict[str, int]] = {}
    for char in truth.values():
        sem = variant_map.semantic(char)
        prefs.setdefault(sem, {})
        prefs[sem][char] = prefs[sem].get(char, 0) + 1
    prefs_dir = store_dir / "lm" / "variant_prefs"
    prefs_dir.mkdir(parents=True, exist_ok=True)
    with open(prefs_dir / f"{edition}.json", "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)
    summary["variant_prefs"] = {k: v for k, v in prefs.items()
                                if len(v) > 1}   # 只汇报有多形体的

    # 4) 确认语料导出（语义层）：只导出全列已确认的列
    by_col: dict[tuple, list] = {}
    for inst in instances:
        by_col.setdefault((inst.page, inst.col), []).append(inst)
    lines: list[str] = []
    for key in sorted(by_col,
                      key=lambda k: (reading_order_key(
                          parse_id(by_col[k][0].id))[0], k[1])):
        col_insts = sorted(by_col[key], key=lambda i: i.idx)
        chars = [truth.get(i.id) for i in col_insts]
        if all(chars):
            lines.append(variant_map.normalize_text("".join(chars)))
    corpus_dir = store_dir / "lm" / "corpus_confirmed"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    (corpus_dir / f"{book}.txt").write_text("\n".join(lines),
                                            encoding="utf-8")
    summary["corpus_columns"] = len(lines)

    # 5) 簇级问题标记汇总：切分/聚类缺陷清单，供 Phase 3 参数迭代
    if state.cluster_flags:
        by_flag: dict[str, list[str]] = {}
        for cid, flag in sorted(state.cluster_flags.items()):
            by_flag.setdefault(flag, []).append(cid)
        flags_path = book_dir / "phase7_review" / "flags.json"
        with open(flags_path, "w", encoding="utf-8") as f:
            json.dump(by_flag, f, ensure_ascii=False, indent=2)
        summary["cluster_flags"] = {k: len(v) for k, v in by_flag.items()}

    return summary
