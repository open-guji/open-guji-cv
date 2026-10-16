"""M7 反馈事件流：标签事件重放 / 簇号重绑 / 追加读写。

labels.jsonl（只追加）是唯一真源，当前标注状态 = 重放事件流。
事件类型：confirm / relabel / split / merge / mark / flag（见设计文档 9.3）。
flag 为簇级问题标记：impure（不同字混簇）/ truncated（截断不完整）/
contaminated（边框或邻字混入）/ not_text（非文字）。

v1 的 `run_update`（消费标签更新四类下游资产）、阈值标定 `calibrate_threshold`、
`derive_truth` 随 v1 聚类链于 2026-10-06 删除（overview#418）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path



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
        # 法定人数：得票成员不足原成员半数 → 事件失效，保留原簇号
        # （原簇号已不存在，重放时自然无效）。宁可失效也不错绑——
        # 实测一个 impure 标记曾错绑到 140 人大簇，生成 9742 个
        # 「同字对」毒化标定金集。
        if votes[best] < max(2, 0.5 * len(members)):
            out.append(ev)
            continue
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
