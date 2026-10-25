"""意见池的数据形（设计第二节）：``guji-opinion/0.1`` 意见、log 事件、判定记录、状态推导。

- 意见（opinions.jsonl 一行）只追加，同 id 不重写；要改就在 log 记 ``superseded`` 再追加新 id。
- 状态不另存，由 log 推出来（``derive_status``）。
- 判定记录（log ``triaged`` 的 data）见 ``Triage``。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import asdict, dataclass, field, fields

SCHEMA = "guji-opinion/0.1"

#: 渠道；机器意见写 ``machine:<检查名>``
CHANNELS = ("charfix", "span", "cellreview", "feedback")
# figure：读者说这格是图形不是字（GUJI-737 图片格），只交用户定
CATEGORIES = ("wrong", "missing", "extra", "order", "seg", "lacuna", "unclear", "punct", "entity", "figure", "other")
LOG_KINDS = ("ingested", "superseded", "dup", "forwarded", "triaged", "decided", "applied", "replied", "cv_written",
             "batched", "pr_opened", "published", "reverted", "policy_applied")
VERDICTS = ("text_ok", "accept", "lacuna_guess", "seg_issue", "out_of_scope", "unclear")
ROUTES = ("auto_accept", "auto_reject", "to_user", "discuss", "forward")
DECISIONS = ("accept", "reject", "discuss")
#: 修订分类；B′（mark→lacuna 格）用撇号 U+2032，输入 ``B'`` 也认
REV_CLASSES = ("A", "B", "B′", "C")
PROFILES = ("published", "proofing")
#: 意见状态（``derive_status`` 的值）
STATUSES = ("new", "to_normalize", "superseded", "dup", "forwarded", "auto_accepted", "auto_rejected",
            "to_user", "discussing", "accepted", "rejected", "applied", "reverted")

CELL_RE = re.compile(r"^\d+:\d+:-?[1-9]\d*[ab]?$")
VOL_RE = re.compile(r"^\d{3}$")
ID_RE = re.compile(r"^op_[a-z0-9:_-]+_[0-9a-f]{10}(?:_\d+)?$")


class SchemaError(ValueError):
    pass


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ms_to_iso(ms) -> str:
    """网站记录的毫秒时间戳 → ISO（UTC，到秒）。已是字符串的原样返回。"""
    if isinstance(ms, str):
        return ms
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_class(c: str | None) -> str | None:
    if c is None:
        return None
    c = str(c).strip()
    return "B′" if c in ("B'", "B’", "Bp", "B′") else c


def make_id(channel: str, source_key: str, seq: int | None = None) -> str:
    """``op_<渠道>_<来源键 sha1 前 10 位>[_<序号>]``。

    来源键由 ``ingest`` 按渠道拼成规范形（见 ``ingest.source_key``）：同一条读者意见不管从中心库快照
    还是网站公开实时读进来，来源键相同、id 相同，所以不会入池两次。机器意见渠道里的冒号换成 ``-``。"""
    ch = channel.replace(":", "-")
    h = hashlib.sha1(source_key.encode("utf-8")).hexdigest()[:10]
    return f"op_{ch}_{h}" + (f"_{seq}" if seq is not None else "")


def cell_key(a: str) -> tuple:
    """格位排序键：页、列、格、子列。"""
    p, c, s = a.split(":")
    sub = s[-1] if s[-1:] in ("a", "b") else ""
    return (int(p), int(c), int(s[:-1] if sub else s), sub)


@dataclass
class Opinion:
    id: str
    book: str
    vol: str
    channel: str
    raw_id: str
    ts: str
    target: dict
    category: str
    voter: str | None = None
    proposal: dict | None = None
    note: str | None = None
    normalized_by: str | None = None
    created_at: str = ""
    #: 渠道特有的原始字段（精校票的 choice／shown／pick_src，fb_ 的 pageUrl 等），只作参考
    extra: dict | None = None
    schema: str = SCHEMA

    def errors(self) -> list[str]:
        e = []
        if self.schema != SCHEMA:
            e.append(f"schema 应为 {SCHEMA}")
        if not ID_RE.match(self.id or ""):
            e.append(f"id 不合规：{self.id!r}")
        if not self.book:
            e.append("缺 book")
        if not (self.channel in CHANNELS or str(self.channel).startswith("machine:")):
            e.append(f"channel 不认识：{self.channel!r}")
        if self.channel != "feedback" and not VOL_RE.match(self.vol or ""):
            e.append(f"vol 应为三位章号：{self.vol!r}")
        if not self.raw_id:
            e.append("缺 raw_id")
        if self.category not in CATEGORIES:
            e.append(f"category 不认识：{self.category!r}")
        t = self.target if isinstance(self.target, dict) else None
        if t is None:
            e.append("target 应为对象")
        else:
            for k in ("start", "end"):
                v = t.get(k)
                if v is not None and not CELL_RE.match(str(v)):
                    e.append(f"target.{k} 不是格位：{v!r}")
            if (t.get("start") is None) != (t.get("end") is None):
                e.append("target 的 start、end 要么都有要么都没有")
            if t.get("start") and not (t.get("text_version") or t.get("rev") or t.get("entity_version")):
                e.append("有格号的 target 要带 text_version 或 rev（专名意见带 entity_version）")
        if self.proposal is not None and not isinstance(self.proposal, dict):
            e.append("proposal 应为对象")
        if not self.ts:
            e.append("缺 ts")
        return e

    def validate(self) -> Opinion:
        e = self.errors()
        if e:
            raise SchemaError(f"{self.id}: " + "；".join(e))
        return self

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None and v != {} or k in ("target",)}

    @classmethod
    def from_dict(cls, d: dict) -> Opinion:
        names = {f.name for f in fields(cls)}
        unknown = set(d) - names
        if unknown:
            raise SchemaError(f"意见 {d.get('id')} 有不认识的字段：{sorted(unknown)}")
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class LogEvent:
    ts: str
    opinion: str
    kind: str
    by: str
    data: dict = field(default_factory=dict)

    def errors(self) -> list[str]:
        e = []
        if self.kind not in LOG_KINDS:
            e.append(f"kind 不认识：{self.kind!r}")
        if not self.opinion:
            e.append("缺 opinion")
        if not self.by:
            e.append("缺 by")
        d = self.data or {}
        if self.kind == "superseded" and not d.get("by"):
            e.append("superseded 要带 data.by（取代它的新 id）")
        if self.kind == "dup" and not d.get("of"):
            e.append("dup 要带 data.of")
        if self.kind == "forwarded" and not d.get("to"):
            e.append("forwarded 要带 data.to")
        if self.kind == "triaged":
            e += Triage.from_dict(d).errors()
        if self.kind == "decided" and d.get("decision") not in DECISIONS:
            e.append(f"decided 的 decision 应为 {DECISIONS}")
        if self.kind == "applied" and not d.get("text_version"):
            e.append("applied 要带 data.text_version")
        if self.kind in ("batched", "pr_opened", "published", "reverted") and not d.get("release"):
            e.append(f"{self.kind} 要带 data.release")
        if self.kind == "pr_opened" and not d.get("pr"):
            e.append("pr_opened 要带 data.pr")
        if self.kind == "reverted" and not d.get("reason"):
            e.append("reverted 要带 data.reason")
        return e

    def validate(self) -> LogEvent:
        e = self.errors()
        if e:
            raise SchemaError(f"log {self.kind} {self.opinion}: " + "；".join(e))
        return self

    def to_dict(self) -> dict:
        return {"ts": self.ts, "opinion": self.opinion, "kind": self.kind, "by": self.by, "data": self.data or {}}

    @classmethod
    def from_dict(cls, d: dict) -> LogEvent:
        return cls(ts=d.get("ts", ""), opinion=d.get("opinion", ""), kind=d.get("kind", ""),
                   by=d.get("by", ""), data=d.get("data") or {})


@dataclass
class Triage:
    """判定记录（总设计 §5.4、本设计 2.4）。"""
    verdict: str
    confidence: float
    rationale_public: str
    route: str
    judge: str
    profile: str = "published"
    rationale_internal: str = ""
    evidence: dict | str | None = None
    revision: dict | None = None
    reply_draft: str = ""
    engine: str = ""
    #: 规则表给出的理由（为什么是这个 route），工具写
    rule: list | None = None
    #: 起草的 CV 人裁事件（采纳后进 cv_events_todo，第二阶段补写）
    draft_event: dict | None = None
    #: 证据里一致的路数（字形库前一名、整理本、上下文…），自动采纳门槛用
    evidence_agree: int | None = None

    def errors(self) -> list[str]:
        e = []
        if self.verdict not in VERDICTS:
            e.append(f"verdict 应为 {VERDICTS}")
        try:
            c = float(self.confidence)
            if not 0 <= c <= 1:
                e.append("confidence 应在 0–1")
        except (TypeError, ValueError):
            e.append("confidence 不是数")
        if self.route not in ROUTES:
            e.append(f"route 应为 {ROUTES}")
        if self.profile not in PROFILES:
            e.append(f"profile 应为 {PROFILES}")
        if not self.judge:
            e.append("缺 judge")
        if self.route in ("auto_accept", "auto_reject") and not (self.rationale_public or "").strip():
            e.append("自动结案必须带一句公开理由")
        r = self.revision
        if r is not None:
            if not isinstance(r, dict) or norm_class(r.get("class")) not in REV_CLASSES:
                e.append(f"revision.class 应为 {REV_CLASSES}")
            elif not isinstance(r.get("cells"), list) or not r["cells"]:
                e.append("revision.cells 不能空")
        return e

    def to_dict(self) -> dict:
        d = asdict(self)
        if d.get("revision"):
            d["revision"] = dict(d["revision"], **{"class": norm_class(d["revision"].get("class"))})
        return {k: v for k, v in d.items() if v not in (None, "", [])}

    @classmethod
    def from_dict(cls, d: dict) -> Triage:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names},
                   **{k: "" for k in ("verdict", "route", "judge", "rationale_public")
                      if k not in (d or {})}, **({"confidence": -1} if "confidence" not in (d or {}) else {}))


_ROUTE_STATUS = {"auto_accept": "auto_accepted", "auto_reject": "auto_rejected", "to_user": "to_user",
                 "discuss": "discussing", "forward": "forwarded"}
_DECISION_STATUS = {"accept": "accepted", "reject": "rejected", "discuss": "discussing"}


def derive_status(events: list[LogEvent]) -> str:
    """一条意见的 log（按写入顺序）→ 状态。

    ``new → triaged →（auto_accepted｜auto_rejected｜to_user｜discussing｜forwarded｜dup）→ accepted／rejected → applied``；
    ``fb_`` 入池时待规整（``to_normalize``），规整后原条 ``superseded``。``replied``、``cv_written``、``batched``、``pr_opened``、``published``、``policy_applied`` 不改状态
    （发布批的进度看 ``releases.jsonl``）；``reverted`` 把 applied 退回。"""
    st = "new"
    for e in events:
        k, d = e.kind, e.data or {}
        if k == "ingested":
            if st == "new" and d.get("pending_normalize"):
                st = "to_normalize"
        elif k == "superseded":
            st = "superseded"
        elif k == "dup":
            st = "dup"
        elif k == "forwarded":
            st = "forwarded"
        elif k == "triaged":
            st = _ROUTE_STATUS.get(d.get("route"), st)
        elif k == "decided":
            st = _DECISION_STATUS.get(d.get("decision"), st)
        elif k == "applied":
            st = "applied"
        elif k == "reverted":
            st = "reverted"
    return st


def json_schema() -> dict:
    """``guji-opinion/0.1`` 的 JSON Schema（给网站和别的仓对照用）。"""
    cell = {"type": "string", "pattern": CELL_RE.pattern}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://open-guji.org/schema/opinion/v0.1.json",
        "title": SCHEMA,
        "type": "object",
        "additionalProperties": False,
        "required": ["schema", "id", "book", "vol", "channel", "raw_id", "ts", "target", "category", "created_at"],
        "properties": {
            "schema": {"const": SCHEMA},
            "id": {"type": "string", "pattern": ID_RE.pattern},
            "book": {"type": "string"},
            "vol": {"type": "string"},
            "channel": {"anyOf": [{"enum": list(CHANNELS)}, {"type": "string", "pattern": "^machine:[A-Za-z0-9_.-]+$"}]},
            "raw_id": {"type": "string"},
            "voter": {"type": "string"},
            "ts": {"type": "string"},
            "target": {"type": "object", "properties": {
                "start": cell, "end": cell, "text_version": {"type": "string"}, "rev": {"type": "string"},
                "entity_version": {"type": "string"},
                "check": {"type": "string"}}},
            "category": {"enum": list(CATEGORIES)},
            "proposal": {"type": "object", "properties": {"text": {"type": "string"}, "choice": {"type": "string"}, "alt": {"type": "string"}}},
            "note": {"type": "string"},
            "normalized_by": {"type": "string"},
            "created_at": {"type": "string"},
            "extra": {"type": "object"},
        },
    }
