"""M7 反馈更新：标签事件流重放 + 聚类阈值标定。

labels.jsonl（只追加）是唯一真源，当前标注状态 = 重放事件流。
事件类型：confirm / relabel / split / merge / mark（见设计文档 9.3）。
"""

from __future__ import annotations

import json
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
    # instance_id -> 标记（damaged / empty / illegible）
    marks: dict[str, str] = field(default_factory=dict)
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
    return state


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
