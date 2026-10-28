"""人裁事件体检：按 `doc/formats/人裁事件规范.md` 逐行查 `feedback/events/`、`feedback/vision/`、`feedback/rulings/`。

只读、不改账。人裁日志只追加，查出来的问题靠追加更正事件解决；改行要连 `consumed/`、金标 `source_events`
一起改（`consumed/` 认的是事件 id），只在一次性规整里做（`migrate_v1`，2026-10-21 把下表的历史遗留清完了）。

`guji events lint -w <工作区>` 打印报告；`--json` 出机读结果。每类问题给条数和前几个例子。

| 代码 | 级别 | 含义 |
|---|---|---|
| `E-parse` | 错 | 行不是 JSON，或过不了 `Event` 信封（kind 不认识、缺字段） |
| `E-dup-id` | 错 | 同一事件 id 出现在不止一个文件、内容不同——`consumed/` 按 id 记账，两条只会消费一条 |
| `E-key-fields` | 错 | `target.book/page/col/slot` 有值但与 `target.key` 解析结果不一致 |
| `E-key-empty` | 错 | `target.key` 解析得出、`target.book/page/col/slot` 却全空（落盘的原行；读回时会补，但库里 `events.book` 列是空的） |
| `E-payload-v` | 错 | `confirm` 没有 `payload.v` 或取值不在规范里 |
| `E-unit` | 错 | kind 与 `target.unit` 不配（如 `cutline` 不是 `boundary`） |
| `E-id-shape` | 错 | id 不是 `evt_<batch>_<seq:06d>` |
| `E-batch-file` | 错 | 事件的 `batch` 与所在文件名不符（`read(batch)` 读不到它，`batch_path` 指向别的文件） |
| `E-client-ts-sec` | 错 | `payload.client_ts` 是秒不是毫秒 |
| `E-product-key` | 错 | `anchor.product_key` 不是 `{step, key, fingerprint}`（切分产物 sha 归 `anchor.cells_sha`） |
| `W-confirm-no-shape` | 警 | `v=confirm` 却没有 `shape`（定字裁决没给字，文本层不认） |
| `W-unconsumed` | 警 | 路由表给了去向、对应消费者却没记账的事件（条数按「事件×消费者」计；例子按批次汇总）。多半是脚本或 Worker 直写、没走 route（规范 §9 F-7），补跑 `guji events route`。`product_invalidate` 按设计不追溯，不报 |
| `I-order` | 提示 | 同一单位的「最终裁决」按批次名序与按时间序不同的条数（读者一律按 `replay_key`） |
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from pydantic import ValidationError

from .events import Event, EventLog, replay_key
from .keys import parse_card_id

#: `confirm` 的 `payload.v` 取值（规范 §5.1）
CONFIRM_V = frozenset({"confirm", "seg_defect", "not_a_char", "skip", "damaged", "figure"})

#: `anchor.product_key` 只许这几个键（规范 §7.2）
PRODUCT_KEY_FIELDS = frozenset({"step", "key", "fingerprint"})

#: kind → 允许的 `target.unit`（规范 §5 各节；没列的不查）
KIND_UNITS = {
    "confirm": {"cell"},
    "cutline": {"boundary"},
    "border_offset": {"page"},
    "band": {"column"},
    "border_class": {"column", "page"},
    "head_raise": {"column"},
    "inverted_band": {"page"},
    "n_body_slots": {"column"},
    "vision_check": {"cell"},
    "ctx_ruling": {"cell"},
    "collate_verdict": {"cell"},
    "collate_ok": {"cell"},
    "cell_review": {"cell"},
    "needs_review": {"cell"},
    "figure_region": {"page"},
}

_ID = re.compile(r"^evt_(?P<batch>.+)_(?P<seq>\d{6,})$")
_EXAMPLES = 5


class Report:
    def __init__(self) -> None:
        self.n_files = 0
        self.n_events = 0
        self.counts: Counter[str] = Counter()
        self.examples: dict[str, list[str]] = defaultdict(list)

    def add(self, code: str, example: str) -> None:
        self.counts[code] += 1
        if len(self.examples[code]) < _EXAMPLES:
            self.examples[code].append(example)

    @property
    def n_errors(self) -> int:
        return sum(n for c, n in self.counts.items() if c.startswith("E-"))

    def to_dict(self) -> dict:
        return {"files": self.n_files, "events": self.n_events, "errors": self.n_errors,
                "counts": dict(sorted(self.counts.items())),
                "examples": {c: self.examples[c] for c in sorted(self.examples)}}

    def render(self) -> str:
        lines = [f"扫了 {self.n_files} 个文件、{self.n_events} 条事件；错 {self.n_errors} 条"]
        for code in sorted(self.counts):
            lines.append(f"  {code:20s} {self.counts[code]:6d}")
            for ex in self.examples[code]:
                lines.append(f"      {ex}")
        return "\n".join(lines)


def _check_event(e: Event, where: str, rep: Report) -> None:
    m = _ID.match(e.id)
    if not m or m["batch"] != e.batch or int(m["seq"]) != e.seq:
        rep.add("E-id-shape", f"{where} {e.id}（batch={e.batch} seq={e.seq}）")
    t = e.target
    want = parse_card_id(t.key)
    if want:
        got = {k: getattr(t, k) for k in ("book", "page", "col", "slot")}
        bad = [k for k, v in got.items() if v is not None and want.get(k) is not None and v != want[k]]
        if bad:
            rep.add("E-key-fields", f"{where} {e.id} key={t.key} " + ", ".join(f"{k}={got[k]!r}" for k in bad))
    units = KIND_UNITS.get(e.kind)
    if units and t.unit not in units:
        rep.add("E-unit", f"{where} {e.id} kind={e.kind} unit={t.unit}")
    p = e.payload or {}
    if e.kind == "confirm":
        v = p.get("v")
        if v not in CONFIRM_V:
            rep.add("E-payload-v", f"{where} {e.id} v={v!r}")
        elif v == "confirm" and not p.get("shape"):
            rep.add("W-confirm-no-shape", f"{where} {e.id} key={t.key}")
    ct = p.get("client_ts")
    if isinstance(ct, (int, float)) and not isinstance(ct, bool) and 0 < ct < 1e11:
        rep.add("E-client-ts-sec", f"{where} {e.id} client_ts={ct}")
    pk = (t.anchor or {}).get("product_key")
    if pk is not None and not (isinstance(pk, dict) and set(pk) <= PRODUCT_KEY_FIELDS):
        rep.add("E-product-key", f"{where} {e.id} product_key 键={sorted(pk) if isinstance(pk, dict) else type(pk).__name__}")


def lint_dir(d: Path, rep: Report, seen: dict[str, tuple[str, str]], events: list[Event]) -> None:
    for f in sorted(d.glob("*.jsonl")):
        rep.n_files += 1
        stem = f.stem
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            where = f"{d.name}/{f.name}:{n}"
            rep.n_events += 1
            try:
                e = Event.model_validate_json(line)
            except (ValidationError, ValueError) as exc:
                rep.add("E-parse", f"{where} {str(exc).splitlines()[0][:120]}")
                continue
            if EventLog.safe_batch_name(e.batch) != stem:
                rep.add("E-batch-file", f"{where} batch={e.batch!r}")
            raw_t = json.loads(line).get("target") or {}
            if all(raw_t.get(k) is None for k in ("book", "page", "col", "slot")) and parse_card_id(e.target.key):
                rep.add("E-key-empty", f"{where} {e.id} key={e.target.key}")
            body = json.dumps(e.model_dump(mode="json", exclude={"id"}), sort_keys=True, ensure_ascii=False)
            prev = seen.get(e.id)
            if prev is not None and prev[1] != body:
                rep.add("E-dup-id", f"{where} {e.id} 又见于 {prev[0]}")
            seen.setdefault(e.id, (where, body))
            _check_event(e, where, rep)
            events.append(e)


def order_disagreements(events: list[Event]) -> int:
    """同一 (kind, unit, key) 的最终裁决按 `Event.order`（批次名序）与按 `replay_key`（时间序）取到不同 payload 的单位数。"""
    groups: dict[tuple, list[Event]] = defaultdict(list)
    for e in events:
        groups[(e.kind, e.target.unit, e.target.key)].append(e)
    n = 0
    for evs in groups.values():
        if len({e.batch for e in evs}) < 2:
            continue
        if max(evs, key=lambda e: e.order).payload != max(evs, key=replay_key).payload:
            n += 1
    return n


def lint(feedback_root: Path) -> Report:
    rep = Report()
    seen: dict[str, tuple[str, str]] = {}
    events: list[Event] = []
    for sub in ("events", "vision", "rulings"):
        d = Path(feedback_root) / sub
        if d.is_dir():
            lint_dir(d, rep, seen, events)
    k = order_disagreements(events)
    if k:
        rep.counts["I-order"] = k
    unconsumed(Path(feedback_root), events, rep)
    return rep


#: 新接上路由时历史事件不追溯的消费者（见 `consumers.product_invalidate` 文档）：没记账不算漏
NOT_RETROACTIVE = frozenset({"product_invalidate"})


def unconsumed(feedback_root: Path, events: list[Event], rep: Report) -> None:
    """`W-unconsumed`：有去向却没消费的（规范 §9 F-7）。"""
    from .consumers import CONSUMERS
    from .routes import RouteTable
    if not events:
        return
    table = RouteTable.load(feedback_root / "routes.yaml")
    log = EventLog(feedback_root)
    dests = {e.id: {d.consumer for d in table.destinations(e)} for e in events}
    by: Counter[tuple[str, str]] = Counter()
    for consumer in CONSUMERS:
        if consumer in NOT_RETROACTIVE:
            continue
        done = log.consumed_ids(consumer)
        for e in events:
            if consumer in dests[e.id] and e.id not in done:
                by[(consumer, e.batch)] += 1
    if by:
        rep.counts["W-unconsumed"] = sum(by.values())
        rep.examples["W-unconsumed"] = [f"{c} ← {b}：{n} 条" for (c, b), n in by.most_common(_EXAMPLES)]
