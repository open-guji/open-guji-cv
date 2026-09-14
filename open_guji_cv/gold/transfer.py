"""裁决表 ⇄ 测试集：两个**显式**动作，都不在管线运行路径上。

三仓边界（用户 2026-09-13 裁定，正本 overview `进度/数据边界-三仓各管什么.md`）：

- workspace `feedback/verdicts/<shard>/`：人裁事件经路由消费后的落点（`consumers.gold_add`）。
  管线回流、面板去重读这里。它是事件日志的派生物——`rebuild_verdicts` 能从事件重放。
- open-guji-dataset `<shard>/`：测试集，只放**显式导入**的条目，运行时不读不写。
  `import_to_dataset` 是唯一往里写人裁数据的入口（迁移旧载体的 `GoldStore.migrate` 另算）。

两边载体同格式（`GoldItem` 信封），导入就是挑一批复制，不转格式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .item import GoldItem
from .store import GoldStore


def parse_pages(expr: str | None) -> set[int] | None:
    """`"1-50,60,70-72"` → 页号集合；空 / None → None（不过滤）。"""
    if not expr:
        return None
    out: set[int] = set()
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


@dataclass
class ImportFilter:
    book: str | None = None
    pages: set[int] | None = None
    stratum: str | None = None
    ids: set[str] | None = None
    include_uncertain: bool = False     # 默认只导 active；idk/uncertain 不进测试集

    def accept(self, it: GoldItem) -> bool:
        if it.status == "retired" or it.status == "stale":
            return False
        if it.status == "uncertain" and not self.include_uncertain:
            return False
        if self.book and str(it.anchor.book) != self.book:
            return False
        if self.pages is not None and it.anchor.page not in self.pages:
            return False
        if self.stratum and it.stratum != self.stratum:
            return False
        if self.ids is not None and it.id not in self.ids:
            return False
        return True


@dataclass
class TransferResult:
    shard: str
    n_source: int = 0
    n_selected: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    dry_run: bool = False
    sample_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"shard": self.shard, "source": self.n_source, "selected": self.n_selected,
                "added": self.added, "updated": self.updated, "unchanged": self.unchanged,
                "dry_run": self.dry_run, "sample_ids": self.sample_ids}


def import_to_dataset(shard: str, src: GoldStore, dst: GoldStore, flt: ImportFilter | None = None,
                      why: str = "", dry_run: bool = False) -> TransferResult:
    """把 workspace 裁决表 `shard` 里符合过滤条件的条目复制进 dataset 同名分片。

    合并口径与 `consumers.gold_add` 一致：目标分片里已有同 id 条目时，`expected` /
    `input` 按键合并（旧值打底、新值覆盖），不整体替换——v1 时代的字段不能被抹掉
    （2026-09-04 教训，见 gold_add）。`source_events` 由 `GoldStore.upsert` 并集。
    """
    flt = flt or ImportFilter()
    res = TransferResult(shard=shard, dry_run=dry_run)
    items = src.list(shard, legacy=False)
    res.n_source = len(items)
    picked = [it.model_copy(deep=True) for it in items if flt.accept(it)]
    res.n_selected = len(picked)
    res.sample_ids = [it.id for it in picked[:5]]
    if not picked:
        return res
    prev = {i.id: i for i in dst.list(shard)}
    for it in picked:
        old = prev.get(it.id)
        if old is None:
            res.added += 1
            continue
        it.expected = {**old.expected, **it.expected}
        it.input = {**(old.input or {}), **(it.input or {})}
        if old.expected == it.expected and old.status == it.status:
            res.unchanged += 1
        else:
            res.updated += 1
    if dry_run:
        return res
    dst.upsert(shard, picked, why or "显式导入测试集（guji gold import）")
    return res


def rebuild_verdicts(log, store: GoldStore, table=None, batches: Iterable[str] | None = None,
                     why: str = "从事件日志重放") -> dict:
    """事件日志 → 裁决表：把所有（或指定批次的）事件按路由表重放给 `gold_add`。

    **不看 consumed 记账**——记账是「这条事件消费过没有」，而这里是重建派生物，
    事件本身就是真源。幂等：`gold_add` 按 id upsert，重放两遍结果一样。
    """
    from ..feedback.consumers import gold_add
    from ..feedback.routes import RouteTable

    table = table or RouteTable.load(log.root / "routes.yaml")
    wanted = set(batches) if batches else None
    events = [e for e in log.iter_all() if wanted is None or e.batch in wanted]
    events.sort(key=lambda e: e.order)
    plan = table.plan(events)
    pairs = plan.get("gold_add", [])
    res = gold_add(pairs, store=store, why=why)
    return {"events": len(events), "routed_to_gold_add": len(pairs), **res.to_dict()}
