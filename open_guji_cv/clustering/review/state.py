"""审查会话状态：装配 phase4~6 数据 + labels.jsonl 事件流。

纯逻辑层（不含 HTTP），API 数据组装与事件写入都在这里，便于单测。
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ..extractor import CharInstance, load_index
from ..feedback import LabelState, append_event, load_events, replay_events

VALID_OPS = {"confirm", "relabel", "split", "merge", "mark"}


class ReviewSession:
    def __init__(self, book_out_dir: str | Path):
        self.book_dir = Path(book_out_dir)
        self.labels_path = self.book_dir / "phase7_review" / "labels.jsonl"
        self._load()

    # ── 数据装配 ─────────────────────────────────────────

    def _load(self) -> None:
        self.instances: dict[str, CharInstance] = {
            i.id: i for i in load_index(self.book_dir / "phase4_chars")}

        with open(self.book_dir / "phase5_clusters" / "clusters.json",
                  encoding="utf-8") as f:
            payload = json.load(f)
        self.clusters: dict[str, dict] = {
            c["cluster_id"]: c for c in payload["clusters"]}
        self.cluster_of: dict[str, str] = {}
        for c in payload["clusters"]:
            for m in c["members"]:
                self.cluster_of[m] = c["cluster_id"]

        phase6 = self.book_dir / "phase6_labels"
        self.candidates: dict[str, list[dict]] = {}
        cand_path = phase6 / "candidates.json"
        if cand_path.exists():
            with open(cand_path, encoding="utf-8") as f:
                for c in json.load(f)["clusters"]:
                    self.candidates[c["cluster_id"]] = c["candidates"]

        self.ranked: dict[str, dict] = {}
        ranked_path = phase6 / "ranked.json"
        if ranked_path.exists():
            with open(ranked_path, encoding="utf-8") as f:
                for r in json.load(f)["results"]:
                    self.ranked[r["id"]] = r

        self.suspects: list[dict] = []
        suspects_path = phase6 / "suspects.json"
        if suspects_path.exists():
            with open(suspects_path, encoding="utf-8") as f:
                self.suspects = json.load(f)["suspects"]

        self.state: LabelState = replay_events(load_events(self.labels_path))

    # ── 事件 ─────────────────────────────────────────────

    def post_event(self, event: dict) -> dict:
        """校验并追加事件；返回写入的完整事件（含时间戳）。"""
        op = event.get("op")
        if op not in VALID_OPS:
            raise ValueError(f"未知事件类型: {op!r}")
        if op in ("confirm", "split") and event.get("cluster") not in self.clusters:
            raise ValueError(f"未知簇: {event.get('cluster')!r}")
        if op in ("relabel", "mark") and event.get("instance") not in self.instances:
            raise ValueError(f"未知实例: {event.get('instance')!r}")
        if op == "merge":
            for cid in event.get("clusters", []):
                if cid not in self.clusters:
                    raise ValueError(f"未知簇: {cid!r}")
        if op in ("confirm", "relabel") and not event.get("char"):
            raise ValueError("缺少 char 字段")

        full = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                **event}
        append_event(self.labels_path, full)
        self.state = replay_events(load_events(self.labels_path))
        return full

    # ── API 数据组装 ─────────────────────────────────────

    def summary(self) -> dict:
        labeled = sum(1 for cid in self.clusters
                      if self.state.cluster_labels.get(
                          self.state.merged_into.get(cid, cid)))
        labeled_instances = sum(
            1 for iid, cid in self.cluster_of.items()
            if self.state.label_of(iid, cid))
        return {
            "book": self.book_dir.name,
            "n_clusters": len(self.clusters),
            "n_instances": len(self.instances),
            "labeled_clusters": labeled,
            "labeled_instances": labeled_instances,
            "n_suspects": len(self.suspects),
            "n_events": len(load_events(self.labels_path)),
        }

    def queue(self, reason: str | None = None, limit: int = 50) -> list[dict]:
        """审查队列：suspects 按簇聚合，预期收益降序，跳过已标注簇。"""
        by_cluster: dict[str, dict] = {}
        for s in self.suspects:
            cid = s.get("cluster")
            if cid is None:
                continue
            if reason and reason not in s["reasons"]:
                continue
            root = self.state.merged_into.get(cid, cid)
            if self.state.cluster_labels.get(root):
                continue   # 已确认的簇不再进队列
            entry = by_cluster.setdefault(cid, {
                "cluster_id": cid,
                "size": self.clusters[cid]["size"],
                "reasons": set(), "expected_gain": 0.0,
                "best": s.get("best")})
            entry["reasons"].update(s["reasons"])
            entry["expected_gain"] += s.get("expected_gain", 0.0)
        out = sorted(by_cluster.values(), key=lambda e: -e["expected_gain"])
        for e in out:
            e["reasons"] = sorted(e["reasons"])
            e["expected_gain"] = round(e["expected_gain"], 2)
            e["candidates"] = self.candidates.get(e["cluster_id"], [])[:3]
        return out[:limit]

    def cluster_detail(self, cluster_id: str) -> dict:
        c = self.clusters.get(cluster_id)
        if c is None:
            raise KeyError(cluster_id)
        root = self.state.merged_into.get(cluster_id, cluster_id)
        removed = self.state.removed.get(cluster_id, set())
        members = []
        for iid in c["members"]:
            inst = self.instances.get(iid)
            r = self.ranked.get(iid, {})
            members.append({
                "id": iid,
                "page": inst.page if inst else None,
                "col": inst.col if inst else None,
                "idx": inst.idx if inst else None,
                "best": r.get("best"),
                "margin": r.get("margin"),
                "removed": iid in removed,
                "label": self.state.label_of(iid, cluster_id),
            })
        return {
            "cluster_id": cluster_id,
            "size": c["size"],
            "cohesion": c.get("cohesion"),
            "label": self.state.cluster_labels.get(root),
            "candidates": self.candidates.get(cluster_id, []),
            "unsure_neighbors": c.get("unsure_neighbors", []),
            "members": members,
        }

    def context(self, instance_id: str, window: int = 3) -> dict:
        """上下文视图：同列前后 window 个实例（含各自当前最优字）。"""
        inst = self.instances.get(instance_id)
        if inst is None:
            raise KeyError(instance_id)
        col_insts = sorted(
            (i for i in self.instances.values()
             if i.page == inst.page and i.col == inst.col),
            key=lambda i: i.idx)
        pos = next(k for k, i in enumerate(col_insts) if i.id == instance_id)
        lo = max(0, pos - window)
        neighbors = []
        for i in col_insts[lo:pos + window + 1]:
            r = self.ranked.get(i.id, {})
            cid = self.cluster_of.get(i.id)
            neighbors.append({
                "id": i.id, "idx": i.idx,
                "is_target": i.id == instance_id,
                "best": self.state.label_of(i.id, cid) or r.get("best"),
            })
        return {"id": instance_id, "page": inst.page, "col": inst.col,
                "neighbors": neighbors}

    # ── 图块路径解析（HTTP 层用）─────────────────────────

    def patch_file(self, instance_id: str) -> Path | None:
        inst = self.instances.get(instance_id)
        if inst is None:
            return None
        p = self.book_dir / "phase4_chars" / inst.patch_path
        return p if p.exists() else None

    def montage_file(self, cluster_id: str) -> Path | None:
        if cluster_id not in self.clusters:
            return None
        p = self.book_dir / "phase5_clusters" / "montage" / f"{cluster_id}.png"
        return p if p.exists() else None
