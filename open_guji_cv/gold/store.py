"""金标分片仓：`<dataset>/<shard>/items.jsonl` + metadata.json。

P1 的范围：add / get / list / update / retire，够事件自动落金标用。
采样器、重键、读旧格式的四个适配器留给 P2。

写法上照顾既有分片：items.jsonl 与老的 samples/NNN、expected.json 并存，
迁移一个分片就是「把老格式读进来、写成 items.jsonl、删适配器」。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from .item import GoldItem


def default_dataset_root() -> Path:
    env = os.environ.get("GUJI_DATASET_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent.parent / "open-guji-dataset"


class GoldStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else default_dataset_root()

    # ── 路径 ─────────────────────────────────────────────────────────
    def shard_dir(self, shard: str) -> Path:
        return self.root / shard

    def items_path(self, shard: str) -> Path:
        return self.shard_dir(shard) / "items.jsonl"

    def metadata_path(self, shard: str) -> Path:
        return self.shard_dir(shard) / "metadata.json"

    # ── 读 ───────────────────────────────────────────────────────────
    def list(self, shard: str) -> list[GoldItem]:
        p = self.items_path(shard)
        if not p.exists():
            return []
        out = []
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(GoldItem.model_validate_json(line))
        return out

    def get(self, shard: str, item_id: str) -> GoldItem | None:
        return next((i for i in self.list(shard) if i.id == item_id), None)

    def shards(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(str(p.parent.relative_to(self.root)).replace("\\", "/")
                      for p in self.root.rglob("items.jsonl"))

    # ── 写 ───────────────────────────────────────────────────────────
    def _write_all(self, shard: str, items: Iterable[GoldItem]) -> int:
        p = self.items_path(shard)
        p.parent.mkdir(parents=True, exist_ok=True)
        items = list(items)
        tmp = p.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it.model_dump(mode="json", exclude_none=True),
                                   ensure_ascii=False, sort_keys=True) + "\n")
        tmp.replace(p)
        return len(items)

    def upsert(self, shard: str, items: Iterable[GoldItem], why: str = "") -> tuple[int, int]:
        """按 id 合并：新条目追加，已存在的更新 expected 并记 history。返回 (新增, 更新)。"""
        existing = {i.id: i for i in self.list(shard)}
        added = updated = 0
        for it in items:
            old = existing.get(it.id)
            if old is None:
                it.touch("created", why)
                existing[it.id] = it
                added += 1
            elif old.expected != it.expected or old.status != it.status:
                it.history = list(old.history)
                it.touch(f"expected {old.expected} → {it.expected}", why)
                it.source_events = sorted(set(old.source_events) | set(it.source_events))
                existing[it.id] = it
                updated += 1
            else:
                merged = sorted(set(old.source_events) | set(it.source_events))
                if merged != old.source_events:
                    old.source_events = merged
                    existing[it.id] = old
        self._write_all(shard, existing.values())
        return added, updated

    def retire(self, shard: str, item_ids: Iterable[str], why: str = "") -> int:
        items = self.list(shard)
        ids = set(item_ids)
        n = 0
        for it in items:
            if it.id in ids and it.status != "retired":
                it.status = "retired"
                it.touch("retired", why)
                n += 1
        self._write_all(shard, items)
        return n

    def mark_stale(self, shard: str, item_ids: Iterable[str], why: str = "") -> int:
        items = self.list(shard)
        ids = set(item_ids)
        n = 0
        for it in items:
            if it.id in ids and it.status == "active":
                it.status = "stale"
                it.touch("stale", why)
                n += 1
        self._write_all(shard, items)
        return n

    # ── 统计 ─────────────────────────────────────────────────────────
    def summary(self, shard: str) -> dict:
        items = self.list(shard)
        by_status: dict[str, int] = {}
        by_origin: dict[str, int] = {}
        by_stratum: dict[str, int] = {}
        for i in items:
            by_status[i.status] = by_status.get(i.status, 0) + 1
            by_origin[i.label_origin] = by_origin.get(i.label_origin, 0) + 1
            if i.stratum:
                by_stratum[i.stratum] = by_stratum.get(i.stratum, 0) + 1
        return {"shard": shard, "n": len(items), "status": by_status,
                "label_origin": by_origin, "stratum": by_stratum}
