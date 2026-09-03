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
    def list(self, shard: str, legacy: bool = True) -> list[GoldItem]:
        """已迁的读 items.jsonl；没迁的用适配器读旧载体（`legacy=False` 关掉）。"""
        p = self.items_path(shard)
        if p.exists():
            out = []
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        out.append(GoldItem.model_validate_json(line))
            return out
        if legacy:
            from .adapters import load_shard
            return load_shard(self.shard_dir(shard))[1]
        return []

    def carrier(self, shard: str) -> str:
        """这个分片现在是什么载体：items / samples_dir / flat_expected / verdicts / unknown。"""
        from .adapters import load_shard
        return load_shard(self.shard_dir(shard))[0]

    def get(self, shard: str, item_id: str) -> GoldItem | None:
        return next((i for i in self.list(shard) if i.id == item_id), None)

    def shards(self, include_legacy: bool = True) -> list[str]:
        """所有分片。include_legacy 时把还没迁的旧载体也算上。

        ⚠️ `samples/NNN/expected.json` 是**分片内的一个样本**，不是分片——枚举时必须
        跳过 samples 层以下的目录，否则每个样本都会冒充一个分片（且它的 expected.json
        会被扁平适配器误读成「字段名即 id」）。
        """
        if not self.root.exists():
            return []

        def ok(p: Path) -> bool:
            parts = p.relative_to(self.root).parts
            return ".git" not in parts and "samples" not in parts[:-1]

        found = {str(p.parent.relative_to(self.root)).replace("\\", "/")
                 for p in self.root.rglob("items.jsonl") if ok(p)}
        if include_legacy:
            for pattern in ("metadata.json", "expected.json", "verdicts*.jsonl"):
                for p in self.root.rglob(pattern):
                    if not ok(p):
                        continue
                    rel = str(p.parent.relative_to(self.root)).replace("\\", "/")
                    if rel != ".":
                        found.add(rel)
        return sorted(found)

    # ── 迁移 ─────────────────────────────────────────────────────────
    def migrate(self, shard: str, dry_run: bool = False) -> dict:
        """旧载体 → items.jsonl。**不删旧文件**——两边并存，人核对过再删。

        重复 id 不静默丢弃：同一 id 的多条**内容不同**时，保留最后一条并把它标成
        `uncertain`、把冲突记进 history（实测 instances 里有 3 处这种矛盾：同一字位
        一轮判 contaminated、另一轮判 not_text）。内容相同的重复直接合并。
        """
        from .adapters import load_shard
        if self.items_path(shard).exists():
            return {"shard": shard, "skipped": "已经是 items.jsonl"}
        carrier, items = load_shard(self.shard_dir(shard))
        if not items:
            return {"shard": shard, "carrier": carrier, "n": 0, "skipped": "读不出条目"}

        merged: dict[str, GoldItem] = {}
        conflicts: list[str] = []
        for it in items:
            prev = merged.get(it.id)
            if prev is None:
                merged[it.id] = it
                continue
            if prev.expected == it.expected:
                continue                      # 完全相同的重复，合并即可
            conflicts.append(it.id)
            it.history = list(prev.history)
            it.touch("conflict", f"同 id 有冲突的旧条目：{prev.expected} vs {it.expected}；"
                                 f"取后者并标 uncertain，待人裁")
            it.status = "uncertain"
            merged[it.id] = it

        out = list(merged.values())
        if not dry_run:
            for it in out:
                if it.status != "uncertain":
                    it.touch("migrated", f"从 {carrier} 迁入")
            self._write_all(shard, out)
        return {"shard": shard, "carrier": carrier, "n_source": len(items), "n": len(out),
                "conflicts": conflicts, "dry_run": dry_run, "sample_id": out[0].id}

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
