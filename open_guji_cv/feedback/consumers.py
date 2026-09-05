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
    if e.kind == "confirm" and p.get("v") == "seg_defect":
        # 切分缺陷：quality 沿用 char-segmentation/instances 的四分类
        # （clean / truncated / contaminated / not_text），不另造词。
        # 字形/文意若已填也一并留着——人看图时顺手认出的字不该丢。
        out = {"quality": p.get("quality") or "contaminated"}
        if p.get("shape"):
            out["shape"] = p["shape"]
        if p.get("reading"):
            out["reading"] = p["reading"]
        return out
    if e.kind == "recrop":
        return {"old_bbox": p.get("old_bbox"), "corrected_bbox": p.get("new_bbox") or p.get("corrected_bbox")}
    return p


def gold_add(events: list[tuple[Event, Destination]], store: GoldStore | None = None,
             why: str = "", dry_run: bool = False) -> ConsumeResult:
    store = store or GoldStore()
    res = ConsumeResult("gold_add", n_events=len(events))
    by_shard: dict[str, list[GoldItem]] = {}
    for e, d in events:
        # `confirm` 事件同时路由给 glyphdb_admit 与这里：定字那部分归前者，
        # 切分缺陷那部分归这里。不分流的话，每条定字都会往 instances 金标里
        # 塞一条没有 quality 的空条目。
        if e.kind == "confirm" and e.payload.get("v") != "seg_defect":
            res.skipped += 1
            continue
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
            # 试算要和真消费口径一致：内容相同的不算「更新」，否则试算说会改 2 条、
            # 真跑却改 0 条，人会以为消费没生效。
            have = {i.id: i.expected for i in store.list(shard)}
            res.added += sum(1 for i in items if i.id not in have)
            res.updated += sum(1 for i in items
                               if i.id in have and have[i.id] != i.expected)
            continue
        # ⚠️ **合并 expected，不整体替换**（2026-09-04）。
        #
        # 同一个字位可能既有 v1 时代的金标（带 review_verdict / layout /
        # defect / healed 等字段），又有新的人裁事件。人裁说的只是「切分
        # 质量是 truncated 还是 clean」，凭什么把别人记的字段一起抹掉？
        # 实测：vol01:22:9:2 被人裁事件覆盖后，v1 的四个字段全没了，
        # `verify_gold_migration` 当成数据丢失报错——**报得对**。
        #
        # 所以按 id 取回旧 expected 打底，新值覆盖同名键，其余保留。
        prev = {i.id: i for i in store.list(shard)}
        for it in items:
            old = prev.get(it.id)
            if old is None:
                continue
            it.expected = {**old.expected, **it.expected}
            # `input` 同理：v1 条目把 seed / 载体信息记在这里，人裁事件不带
            # 这些字段，直接写就会把它们清空（upsert 是整体替换）。
            it.input = {**(old.input or {}), **(it.input or {})}
        a, u = store.upsert(shard, items, why or "由人裁事件自动落入")
        res.added += a
        res.updated += u
    return res


# ── 未实现的两个（显式报错，不静默吞事件）───────────────────────────
def glyphdb_admit(events, db_path: str = "output/glyph.db",
                  dry_run: bool = False, **kw) -> ConsumeResult:
    """`confirm` 事件 → GlyphDB 进库（2026-09-04 接入，此前是桩）。

    这是审查闭环的最后一环：控制台裁决 → Event → 路由 → 这里写库。
    此前只能手动跑 `seed-ingest`，人裁结果与控制台脱节。

    ## 字形 / 释读分开写（用户 2026-09-04 定）

    「碰到已/巳、人/入 这类，先读字形，但是文本录入要按文意录（最好能记录
    这个转换）」。事件 payload 因此带两个值：

    - `shape`：图上刻的形 → `admit_instance(shape=...)`，进 `glyphs` /
      `exemplars` / `GlyphMatcher` 的**字形索引**；
    - `reading`：文意读法 → `admit_instance(char=...)`，进 `admissions.char`
      与 `instances.semantic`。

    两者不同就是一次转换（`conversion=1`）。**字形永远照录**，连已/巳 也不
    例外——字形层的 near_form 护栏本来就是防「形状判据自己会认错」，字形库
    要是被释读污染，将来一个真刻成这形状、该读别的字的实例会错误继承这次的
    释读，字形匹配整条链就失真（charset_and_lm.md §四的实锤）。

    `not_a_char` / `skip` 事件不进库（前者是判非字，后者是存疑跳过）。
    图块从 v2 的 `char_patch` 缓存取——那正是被裁决的那张图。

    ## ⚠️ v2 的 id 必须加前缀，否则会污染 15332 条已有记录

    v1 的 `book:page:col:idx`（idx 从 0、含 margin 格）与 v2 的
    `book:page:col:slot`（slot 从 1）**长得一模一样但指的不是同一格**。
    实测 vol01/24 c1：库里 `vol01:24:1:2` 是「每」，v2 的 `1:2` 是「書」，
    整体差一格——170 个同 id 命中里 **0 个一致**。不隔离就是把 v1 的记录
    按 v2 的口径改写。所以 v2 事件一律以 `v2:` 开头存库，跟 v1 分居两个
    命名空间；将来要合并得先做真正的重键（阶段 B2），不是靠巧合对齐。
    """
    res = ConsumeResult("glyphdb_admit", n_events=len(events))
    admits = [(e, d) for e, d in events
              if e.kind == "confirm" and (e.payload.get("v") or "confirm") == "confirm"]
    res.skipped = len(events) - len(admits)
    if not admits:
        return res
    if dry_run:
        res.added = len(admits)
        return res

    from ..clustering.glyph_db import GlyphDB
    from ..products.cache import ImageCache
    import cv2

    db = GlyphDB(db_path)
    cache = ImageCache()
    for e, _dest in admits:
        shape = e.payload.get("shape") or e.payload.get("char")
        reading = e.payload.get("reading") or shape
        if not shape:
            res.errors.append(f"{e.target.key}: 事件没有字形，跳过")
            res.skipped += 1
            continue
        book = e.target.book or (e.target.key.split(":")[0] if ":" in e.target.key else "")
        # 图块键：p{page}c{col}s{slot}[a|b]，与 Step4 落缓存时一致
        try:
            _b, pg, col, slot = e.target.key.split(":")
            sub = ""
            if slot and slot[-1] in "ab":
                slot, sub = slot[:-1], slot[-1]
            ckey = f"p{int(pg):04d}c{int(col):02d}s{int(slot)}{sub}"
        except Exception as exc:
            res.errors.append(f"{e.target.key}: 键解析不了（{exc}）")
            res.skipped += 1
            continue
        path = cache.get(book, "char_patch", ckey)
        if path is None:
            res.errors.append(f"{e.target.key}: 缓存里没有字块 {ckey}")
            res.skipped += 1
            continue
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            res.errors.append(f"{e.target.key}: 图块读不出来")
            res.skipped += 1
            continue
        # v2 命名空间：见上面「id 必须加前缀」那节
        db_id = e.target.key if e.target.key.startswith("v2:") else f"v2:{e.target.key}"
        ok = db.admit_instance(
            db_id, reading, cv2.imencode(".png", img)[1].tobytes(),
            provenance="human", shape=shape,
            evidence={"event": e.id, "batch": e.batch,
                      "conversion": bool(e.payload.get("conversion")),
                      "shape": shape, "reading": reading},
            page=str(e.target.page or ""), col=int(e.target.col or 0),
            idx=int(e.target.slot or 0))
        if ok:
            res.added += 1
        else:
            res.skipped += 1        # admit_instance 的幂等闸：已进过库
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
                      dry_run: bool = False, **consumer_kw) -> dict:
    """把未消费的事件按路由表分发给各消费者；成功的记账。

    `consumer_kw` 透传给消费者（如 `glyphdb_admit` 的 `db_path`）——测试要
    指向库副本，别动真库。"""
    table = table or RouteTable.load(log.root / "routes.yaml")
    results: list[ConsumeResult] = []
    all_pending: list[Event] = []
    for consumer, fn in CONSUMERS.items():
        pending = log.pending(consumer, batch)
        pairs = [(e, d) for e in pending for d in table.destinations(e) if d.consumer == consumer]
        if not pairs:
            continue
        all_pending.extend(e for e, _ in pairs)
        res = (fn(pairs, store=store, dry_run=dry_run) if consumer == "gold_add"
               else fn(pairs, dry_run=dry_run, **consumer_kw))
        results.append(res)
        if not dry_run and not res.errors:
            log.mark_consumed(consumer, [e for e, _ in pairs], note=batch or "")
    evs = log.read(batch) if batch else list(log.iter_all())
    return {"batch": batch, "dry_run": dry_run,
            "results": [r.to_dict() for r in results],
            "unrouted": [e.id for e in table.unrouted(evs)]}
