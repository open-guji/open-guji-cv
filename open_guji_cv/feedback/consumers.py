"""消费者：把事件落到该去的地方。

P1 只实现 `gold_add`（事件 → 金标条目），另外两个（glyphdb_admit / glyphdb_recrop）
先给出接口与显式的「未实现」，避免路由表里悄悄丢事件。

**幂等**：每个消费者只处理 `EventLog.pending(consumer)` 里的事件，处理完记账。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..gold.item import Anchor, GoldItem
from ..gold.store import GoldStore
from .events import Event, EventLog
from .routes import Destination, RouteTable


@dataclass
class ConsumeResult:
    consumer: str
    n_events: int = 0
    added: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = None   # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []

    def to_dict(self) -> dict:
        return {"consumer": self.consumer, "events": self.n_events, "added": self.added,
                "updated": self.updated, "skipped": self.skipped, "errors": self.errors}


# ── gold_add ─────────────────────────────────────────────────────────
def _expected_of(e: Event) -> dict:
    """事件 payload → 金标 expected。不同 kind 的金标内容不同。"""
    p = dict(e.payload)
    if e.kind == "verdict":
        return {"verdict": p.get("verdict")}
    if e.kind == "band":
        return {"band": p.get("band")}
    if e.kind == "border_class":
        return {"border_class": p.get("border_class") or p.get("verdict")}
    if e.kind == "not_a_char":
        return {"quality": "not_text"}
    if e.kind == "recrop":
        return {"old_bbox": p.get("old_bbox"), "corrected_bbox": p.get("new_bbox") or p.get("corrected_bbox")}
    return p


def gold_add(events: list[tuple[Event, Destination]], store: GoldStore | None = None,
             why: str = "", dry_run: bool = False) -> ConsumeResult:
    store = store or GoldStore()
    res = ConsumeResult("gold_add", n_events=len(events))
    by_shard: dict[str, list[GoldItem]] = {}
    for e, d in events:
        if not d.shard:
            res.skipped += 1
            res.errors.append(f"{e.id}: 路由没给 shard")
            continue
        t = e.target
        item = GoldItem(
            id=t.key,
            anchor=Anchor(book=t.book, page=t.page, col=t.col, slot=t.slot,
                          **(t.anchor or {})),
            expected=_expected_of(e),
            label_origin="human" if e.actor == "user" else ("align" if e.actor == "align" else "model"),
            stratum=e.payload.get("stratum"),
            stratum_weight=e.payload.get("stratum_weight"),
            status="uncertain" if e.payload.get("verdict") in ("idk", "uncertain") else "active",
            source_events=[e.id],
        )
        if d.extra:
            item.input = {**item.input, **d.extra}
        by_shard.setdefault(d.shard, []).append(item)
    for shard, items in by_shard.items():
        if dry_run:
            have = {i.id for i in store.list(shard)}
            res.added += sum(1 for i in items if i.id not in have)
            res.updated += sum(1 for i in items if i.id in have)
            continue
        a, u = store.upsert(shard, items, why or "由人裁事件自动落入")
        res.added += a
        res.updated += u
    return res


# ── 未实现的两个（显式报错，不静默吞事件）───────────────────────────
def glyphdb_admit(events, **kw) -> ConsumeResult:
    res = ConsumeResult("glyphdb_admit", n_events=len(events), skipped=len(events))
    res.errors.append("glyphdb_admit 尚未接入（P1 之后）：请照旧走 `seed-ingest`")
    return res


def glyphdb_recrop(events, **kw) -> ConsumeResult:
    res = ConsumeResult("glyphdb_recrop", n_events=len(events), skipped=len(events))
    res.errors.append("glyphdb_recrop 尚未接入（P1 之后）：请照旧走 `seed-ingest` + build_recrop_shard.py")
    return res


CONSUMERS = {
    "gold_add": gold_add,
    "glyphdb_admit": glyphdb_admit,
    "glyphdb_recrop": glyphdb_recrop,
}


def route_and_consume(log: EventLog, batch: str | None = None,
                      table: RouteTable | None = None,
                      store: GoldStore | None = None,
                      dry_run: bool = False) -> dict:
    """把未消费的事件按路由表分发给各消费者；成功的记账。"""
    table = table or RouteTable.load(log.root / "routes.yaml")
    results: list[ConsumeResult] = []
    all_pending: list[Event] = []
    for consumer, fn in CONSUMERS.items():
        pending = log.pending(consumer, batch)
        pairs = [(e, d) for e in pending for d in table.destinations(e) if d.consumer == consumer]
        if not pairs:
            continue
        all_pending.extend(e for e, _ in pairs)
        res = (fn(pairs, store=store, dry_run=dry_run) if consumer == "gold_add" else fn(pairs))
        results.append(res)
        if not dry_run and not res.errors:
            log.mark_consumed(consumer, [e for e, _ in pairs], note=batch or "")
    evs = log.read(batch) if batch else list(log.iter_all())
    return {"batch": batch, "dry_run": dry_run,
            "results": [r.to_dict() for r in results],
            "unrouted": [e.id for e in table.unrouted(evs)]}
