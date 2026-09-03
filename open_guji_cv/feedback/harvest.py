"""收割：四种历史格式 → 统一事件信封。

    verdicts        审查页 #data 里的 {id: {v, t}}，或 harvest_verdicts.py 导出的 JSONL
    GUJI-SEED-EVENT 种子/对勘审查页的日志行（seed_queue 契约）
    GUJI-SEG-REVIEW 切分审查页的导出行
    marks           patch_review_marks.json 的朱批平表

共同做法：解析 → 生成 (batch, seq) → 映射 kind 与 target → 交给 EventLog.append。
`seq` 用**源里的时间戳排序后的序号**，保证同一批重复收割得到同样的 id（幂等）。

卡片 id 的形态各不相同（`cols:vol02:171` / `vol01:22:5:4` / `book/page:col:idx`），
这里统一解析成 EventTarget 的 book / page / col / slot，解析不出来就只留 key。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from .events import Event, EventTarget, Kind, make_event

# 审查页把裁决嵌在 <script id="data"> 里
_DATA_RE = re.compile(r'<script[^>]*id="data"[^>]*>(.*?)</script>', re.S)
_SEED_PREFIX = "GUJI-SEED-EVENT"
_SEG_PREFIX = "GUJI-SEG-REVIEW"

# 卡片 id → (book, page, col, slot)
_ID_PATTERNS = [
    re.compile(r"^(?P<prefix>[a-z_]+):(?P<book>vol\d+|book\d+):(?P<page>\d+)$"),          # cols:vol02:171
    re.compile(r"^(?P<book>vol\d+|book\d+):(?P<page>\d+):(?P<col>\d+):(?P<slot>-?\d+)(?P<sub>[ab])?$"),  # vol01:22:5:4
    re.compile(r"^(?P<book>vol\d+|book\d+)/(?P<page>\d+):(?P<col>\d+):(?P<slot>-?\d+)$"), # vol01/50:7:21
    re.compile(r"^(?P<book>vol\d+|book\d+):(?P<page>\d+)$"),
]


def parse_card_id(card_id: str) -> dict[str, Any]:
    for pat in _ID_PATTERNS:
        m = pat.match(card_id)
        if m:
            d = m.groupdict()
            out: dict[str, Any] = {"book": d.get("book")}
            for k in ("page", "col", "slot"):
                if d.get(k) is not None:
                    out[k] = int(d[k])
            return out
    return {}


def _target(step: str, unit: str, key: str, extra: dict | None = None) -> EventTarget:
    return EventTarget(step=step, unit=unit, key=key, **parse_card_id(key), **(extra or {}))


# ── verdicts（裁决台）───────────────────────────────────────────────
def from_verdicts(rows: Iterable[dict], batch: str, step: str, unit: str = "page",
                  kind: Kind = "verdict") -> list[Event]:
    """rows: [{"id": …, "verdict": …, "t": 毫秒}]，或 {id: {"v": …, "t": …}} 展开后的。"""
    rows = [r for r in rows if r.get("id") and r.get("verdict") is not None]
    rows.sort(key=lambda r: (r.get("t") or 0, r["id"]))
    out = []
    for i, r in enumerate(rows, 1):
        payload = {"verdict": r["verdict"]}
        for k in ("note", "stratum", "stratum_weight", "band"):
            if r.get(k) is not None:
                payload[k] = r[k]
        out.append(make_event(batch, i, kind, _target(step, unit, r["id"]), payload,
                              source_format="verdicts"))
    return out


def from_page_html(html: str, batch: str, step: str, unit: str = "page",
                   kind: Kind = "verdict") -> list[Event]:
    """审查页 HTML（Artifact read 回来的）→ 事件。读 #data 里的 verdicts。"""
    m = _DATA_RE.search(html)
    if not m:
        raise ValueError("这页里没有 #data —— 确认读的是审查页本身，不是截图或摘要")
    data = json.loads(m.group(1).replace("<\\/", "</"))
    verdicts = data.get("verdicts") or {}
    rows = []
    for cid, v in verdicts.items():
        if isinstance(v, dict):
            rows.append({"id": cid, "verdict": v.get("v"), "t": v.get("t"), "note": v.get("note")})
        else:
            rows.append({"id": cid, "verdict": v, "t": None})
    events = from_verdicts(rows, batch, step, unit, kind)
    # 页面另存的边界（<id>#band）单独出 band 事件
    bands = [(k, v) for k, v in verdicts.items() if k.endswith("#band")]
    n = len(events)
    for i, (k, v) in enumerate(sorted(bands), 1):
        cid = k[: -len("#band")]
        events.append(make_event(batch, n + i, "band", _target(step, "column", cid),
                                 {"band": v if not isinstance(v, dict) else v.get("v")},
                                 source_format="verdicts"))
    return events


# ── GUJI-SEED-EVENT（种子 / 对勘审查页）─────────────────────────────
_SEED_KIND: dict[str, Kind] = {
    "confirm": "confirm", "reject": "relabel", "not_a_char": "not_a_char",
    "recrop": "recrop", "skip": "skip", "note": "note",
}


def from_seed_log(text: str, batch: str, step: str = "cell_shrink") -> list[Event]:
    """审查页日志里的 `GUJI-SEED-EVENT {json}` 行。"""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(_SEED_PREFIX):
            continue
        try:
            rows.append(json.loads(line[len(_SEED_PREFIX):].strip()))
        except json.JSONDecodeError:
            continue
    rows.sort(key=lambda r: (r.get("batch") or "", r.get("seq") or 0, r.get("ts") or ""))
    out = []
    for i, r in enumerate(rows, 1):
        op = r.get("op") or r.get("action") or "confirm"
        iid = r.get("instance_id") or r.get("id") or ""
        payload = {k: v for k, v in r.items()
                   if k not in ("op", "action", "instance_id", "id", "batch", "seq", "ts")}
        out.append(make_event(batch, i, _SEED_KIND.get(op, "note"),
                              _target(step, "cell", iid), payload,
                              source_format="seed", ts=r.get("ts")))
    return out


# ── GUJI-SEG-REVIEW（切分审查页）────────────────────────────────────
# ⚠️ 这个格式跟另外两个不一样：壳导出的是**纯 JSON 行**，前缀在 `t` 字段里
# （`{"t":"GUJI-SEG-REVIEW","id":…,"verdict":…}`，见 artifacts/shells/*.html 的
# eventsText()），不是行前缀。所以 `t` **不是时间戳**，排序不能拿它当数。
def from_seg_log(text: str, batch: str, step: str = "row_segment") -> list[Event]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(_SEG_PREFIX):          # 行前缀形式（若将来壳改成这样）
            line = line[len(_SEG_PREFIX):].strip()
        elif _SEG_PREFIX not in line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(r, dict) and (r.get("t") == _SEG_PREFIX or r.get("id")):
            rows.append(r)
    rows.sort(key=lambda r: str(r.get("id") or ""))   # t 是字面量，只能按 id 排
    out = []
    for i, r in enumerate(rows, 1):
        key = r.get("id") or f"{r.get('book','')}/{r.get('page','')}:{r.get('col','')}:{r.get('idx','')}"
        payload = {k: v for k, v in r.items() if k not in ("id", "t")}
        out.append(make_event(batch, i, "verdict", _target(step, "cell", key), payload,
                              source_format="seg"))
    return out


# ── marks（朱批平表）────────────────────────────────────────────────
# 壳的循环是 无 → s:1 → s:3 → s:2 → 删除，语义 1=切错 3=没问题 2=存疑
# （artifacts/shells/patch_review_shell.html 的 verdict 映射 1→bad, 2→unsure, else→ok）。
_MARK_VERDICT = {1: "bad", 2: "unsure", 3: "ok"}


def from_marks(marks: dict, batch: str, step: str = "cell_shrink") -> list[Event]:
    """`{"vol01/50:7:21": {"s": 1}, …}`，或整份 `{"marks": {...}, "visited": [...]}`。"""
    if "marks" in marks and isinstance(marks.get("marks"), dict):
        marks = marks["marks"]
    out = []
    for i, (key, val) in enumerate(sorted(marks.items()), 1):
        v = val.get("s", val.get("v")) if isinstance(val, dict) else val
        payload = {"verdict": _MARK_VERDICT.get(v, str(v)), "raw": v}
        if isinstance(val, dict) and val.get("note"):
            payload["note"] = val["note"]
        out.append(make_event(batch, i, "verdict", _target(step, "cell", key), payload,
                              source_format="marks"))
    return out


# ── 统一入口 ─────────────────────────────────────────────────────────
def harvest_text(text: str, batch: str, step: str, unit: str = "page",
                 kind: Kind = "verdict") -> list[Event]:
    """自动认格式：HTML / seed 日志 / seg 日志 / verdicts JSONL / marks JSON。"""
    s = text.strip()
    if _SEED_PREFIX in text:
        return from_seed_log(text, batch, step)
    if _SEG_PREFIX in text:
        return from_seg_log(text, batch, step)
    if s.startswith("<") or _DATA_RE.search(text):
        return from_page_html(text, batch, step, unit, kind)
    # 整份 JSON（marks 文件是多行缩进的，不能按「单行」判）
    if s.startswith("{"):
        try:
            d = json.loads(s)
        except json.JSONDecodeError:
            d = None
        # 单行 verdicts JSONL 也是合法 JSON 对象，先按「有 id + verdict」认出来
        if isinstance(d, dict) and "id" in d and ("verdict" in d or "v" in d):
            d = None
        if isinstance(d, dict):
            inner = d.get("marks") if isinstance(d.get("marks"), dict) else d
            vals = list(inner.values())
            if vals and all(isinstance(v, dict) and "s" in v for v in vals):
                return from_marks(d, batch, step)
            if vals and all(isinstance(v, (int, str)) for v in vals):
                return from_marks(d, batch, step)
            return from_verdicts([{"id": k, **(v if isinstance(v, dict) else {"verdict": v})}
                                  for k, v in inner.items()], batch, step, unit, kind)
    rows = [json.loads(l) for l in text.splitlines() if l.strip()]
    return from_verdicts(rows, batch, step, unit, kind)


def to_shell_verdicts(events: list[Event]) -> dict[str, dict]:
    """事件 → 审查壳要的 `{id: {"v": …, "t": 毫秒}}`。

    续裁时把上一轮裁决喂回页面用。**不能直接传扁平的 `{id: "ok"}`**——壳的
    `verdictOf` 取的是 `(state[id]||{}).v`，扁平串会让整轮裁决在页面上全部消失
    （`build_border_gold_reviews.py --verdicts` 现在就是这个 bug）。
    """
    import calendar, time as _t
    out: dict[str, dict] = {}
    for e in sorted(events, key=lambda x: x.order):
        if e.kind == "band":
            out[e.target.key + "#band"] = {"v": e.payload.get("band"), "t": _ms(e.ts)}
        else:
            v = e.payload.get("verdict")
            if v is not None:
                out[e.target.key] = {"v": v, "t": _ms(e.ts)}
    return out


def _ms(ts: str | None) -> int:
    import calendar, time as _t
    if not ts:
        return 0
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return int(calendar.timegm(_t.strptime(ts.replace("+00:00", "Z"), fmt)) * 1000)
        except ValueError:
            continue
    return 0


def harvest_file(path: Path, batch: str, step: str, unit: str = "page",
                 kind: Kind = "verdict") -> list[Event]:
    return harvest_text(Path(path).read_text(encoding="utf-8"), batch, step, unit, kind)
