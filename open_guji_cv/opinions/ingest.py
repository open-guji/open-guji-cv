"""三源入池（设计第三节 ``ingest.py``、A2）：网站记录 → ``guji-opinion/0.1``，幂等。

| 来源 | 位置 | 渠道 |
|---|---|---|
| 改字／一段有问题／专名 | 中心库 ``feedback/lists/web/<书>/fixes.jsonl``（网站 Action 每天同步，一行一个 KV 原值）；或网站公开实时读 ``/api/fixes?book=&volume=`` | ``charfix``／``span``；专名 ``ce`` 入池即 ``forwarded`` |
| 精校票 | 中心库 ``feedback/lists/web/<书>/<rev>.jsonl`` | ``cellreview`` |
| 通用反馈 | 网站公开读 ``/api/feedback``，只收文字类（``category=typo`` 或页面在 ``/read/``）且是本书的 | ``feedback``，入池时「待规整」；原样存进 ``raw-feedback.jsonl`` |

规则（吸收 ai-team ``team/CV/公众意见导入/web_opinions.py`` 的 import 步）：
- 测试票不入池：备注以「【测试】」开头，来源或 aid 含 ``eden-test``，或记录带 ``test: true``；
- 站方隐藏单 ``hidden.txt`` 里的不入池；
- **id**：``op_<渠道>_<来源键 sha1 前 10 位>``。来源键是规范形（书、章、版本、格位、类别、来源哈希前 6 位），
  同一条从中心库快照和公开实时读进来 id 相同，不会入两次。``raw_id`` 照各来源的原样：KV key 去掉 voter，
  公开读是 ``kind~首格~末格~类别~who``；
- 同一来源对同一处改了意见（网站同 key 覆盖）：内容不同就追加 ``<id>_2``，旧条记 ``superseded``；
- **重复**：同章、同格、同版本、同类别、同建议、不同来源的，后来的记 ``dup``（指向最早那条）；
- 读者原话按网站规则脱敏（邮箱、手机、QQ／微信、身份证号）。
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .schema import Opinion, cell_key, make_id, ms_to_iso, now_iso
from .store import OpinionStore

SITE = "https://www.openguji.com"
REV_FILE_RE = re.compile(r"^\d{3}-r\d+\.jsonl$")

#: span 的 sub → 意见类别；标点、分段、标题归标点线，专名归专名线（入池即 forwarded）
SPAN_CATEGORY = {"wrong": "wrong", "missing": "missing", "extra": "extra", "order": "order",
                 "punct": "punct", "para": "punct", "heading": "punct", "entity": "entity",
                 "note": "other", "other": "other"}
FORWARD_TO = {"punct": "punct", "entity": "entity"}
#: 精校票 choice → 类别（六档：char 选字、none 无字、unsure 看不出、cut 切坏、jiazhu／main 正文与夹注搞反）
CHOICE_CATEGORY = {"char": "wrong", "none": "extra", "unsure": "unclear", "cut": "seg", "jiazhu": "seg", "main": "seg",
                   "figure": "figure"}

# ---- 脱敏（与网站 edge-functions/api/feedback.js desensitizeText 同口径）----
_RE_ID_CARD = re.compile(r"(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")
_RE_PHONE = re.compile(r"(?<![\w])(?:\+?86[-\s]?|0086[-\s]?)?1[3-9]\d{9}(?!\d)")
_RE_EMAIL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_RE_QQ_WX_ZH = re.compile(r"(QQ|微信)([\s:：号是为]{0,4})([0-9A-Za-z_-]{5,20})", re.IGNORECASE)
_RE_VX_WX_EN = re.compile(r"\b(vx|wx)([\s:：号是为-]{1,4})([0-9A-Za-z_-]{5,20})", re.IGNORECASE)


def desensitize(text):
    if not isinstance(text, str) or not text:
        return text
    out = _RE_ID_CARD.sub("***", text)
    out = _RE_PHONE.sub("1**********", out)
    out = _RE_QQ_WX_ZH.sub(r"\1\2***", out)
    out = _RE_VX_WX_EN.sub(r"\1\2***", out)
    return _RE_EMAIL.sub("***@***", out)


def is_test(rec: dict) -> bool:
    """验收测试票：备注以「【测试】」开头，来源／aid 含 eden-test，或带 test 标记（web_opinions.is_test 同口径）。"""
    if rec.get("test") is True:
        return True
    for k in ("note", "basis", "content"):
        if str(rec.get(k) or "").startswith("【测试】"):
            return True
    return any("eden-test" in str(rec.get(k) or "") for k in ("aid", "src", "voter", "who"))


def parse_hidden(text: str | None) -> set[str]:
    return {ln.split("#", 1)[0].strip() for ln in (text or "").splitlines()} - {""}


def _hidden(hidden: set[str], prefix: str, voter: str) -> bool:
    """隐藏单的 id 是 ``<前缀>|<voter 全值>``；公开读只有 voter 前 6 位，按前缀比。"""
    if not hidden or not voter:
        return False
    return any(h.startswith(prefix + "|") and h[len(prefix) + 1:].startswith(voter) for h in hidden)


def vol3(v) -> str:
    """章号规整成三位：``vol01``、``1``、``001`` → ``001``。"""
    m = re.search(r"(\d+)$", str(v or ""))
    return f"{int(m.group(1)):03d}" if m else ""


@dataclass
class Incoming:
    """一条网站记录规整后的样子：``op`` 为 None 表示不入池（``drop`` 写原因）。"""
    op: Opinion | None = None
    drop: str | None = None
    forward: str | None = None
    pending_normalize: bool = False
    raw: dict | None = None
    source: str = ""


def _op(channel, book, vol, skey, raw_id, voter, ts, target, category, proposal=None, note=None, extra=None):
    return Opinion(id=make_id(channel, skey), book=book, vol=vol, channel=channel, raw_id=raw_id,
                   voter=voter or None, ts=ms_to_iso(ts) if ts is not None else "", target=target,
                   category=category, proposal=proposal or None, note=desensitize(note) or None,
                   extra=extra or None)


# ---- 改字／一段／专名 ----

def _char_cat_prop(r: dict) -> tuple[str, dict]:
    """改字的类别与建议：读者勾了「这是图形，不是字」（``figure: true``）就是 figure 类，建议里不放字（免得被当成改 □）。"""
    if r.get("figure") is True:
        return "figure", {"choice": "figure", **({"alt": r["alt"]} if r.get("alt") else {})}
    return "wrong", {"text": r.get("new_char")}


def from_fix_record(r: dict, book: str, hidden: set[str] = frozenset(), source: str = "fixes.jsonl") -> Incoming:
    """中心库 ``fixes.jsonl`` 的一行（KV 原值：``{v, kind, book_id, volume, text_version, …, voter, ts}``）。"""
    if r.get("book_id") != book:
        return Incoming(drop="不是本书", source=source)
    if is_test(r):
        return Incoming(drop="测试票", source=source)
    kind, vol, tv, voter = r.get("kind") or "char", str(r.get("volume") or ""), r.get("text_version"), r.get("voter") or ""
    v3, w6 = vol3(vol), voter[:6]
    if kind == "char":
        cell = r.get("cell_id")
        if not cell:
            return Incoming(drop="缺 cell_id", source=source)
        if _hidden(hidden, f"cf|{vol}|{tv}|{cell}", voter):
            return Incoming(drop="站方隐藏", source=source)
        op = _op("charfix", book, v3, f"cf:{book}:{v3}:{tv}:{cell}|{w6}", f"cf:{book}:{vol}:{tv}:{cell}", voter,
                 r.get("ts"), {"start": cell, "end": cell, "text_version": tv, **({"check": r["old_char"]} if r.get("old_char") else {})},
                 *_char_cat_prop(r), r.get("basis"),
                 {"entity_ids": r["entity_ids"]} if r.get("entity_ids") else None)
        return Incoming(op=op, source=source)
    if kind == "span":
        s, e, sub = r.get("start"), r.get("end"), r.get("sub") or "other"
        if not s or not e:
            return Incoming(drop="缺 start/end", source=source)
        if _hidden(hidden, f"cs|{vol}|{tv}|{s}-{e}|{sub}", voter):
            return Incoming(drop="站方隐藏", source=source)
        cat = SPAN_CATEGORY.get(sub, "other")
        op = _op("span", book, v3, f"cs:{book}:{v3}:{tv}:{s}-{e}:{sub}|{w6}", f"cs:{book}:{vol}:{tv}:{s}-{e}:{sub}", voter,
                 r.get("ts"), {"start": s, "end": e, "text_version": tv, **({"check": r["old_text"]} if r.get("old_text") else {})},
                 cat, {"text": r["new_text"]} if r.get("new_text") else None, r.get("note"), {"sub": sub})
        return Incoming(op=op, forward=FORWARD_TO.get(cat), source=source)
    if kind == "entity":
        eid = r.get("entity_id")
        anc = r.get("anchor") or {}
        if not eid:
            return Incoming(drop="缺 entity_id", source=source)
        if _hidden(hidden, f"ce|{vol}|{eid}", voter):
            return Incoming(drop="站方隐藏", source=source)
        ev = r.get("entity_version")
        tgt = {"start": anc.get("start"), "end": anc.get("end"), "entity_version": ev, "check": r.get("text")} \
            if anc.get("start") and anc.get("end") and ev else {}
        op = _op("span", book, v3, f"ce:{book}:{v3}:{eid}|{w6}", f"ce:{book}:{vol}:{eid}", voter, r.get("ts"),
                 {k: v for k, v in tgt.items() if v}, "entity", None, r.get("note"),
                 {"entity_id": eid, **({"target": r["target"]} if r.get("target") else {})})
        return Incoming(op=op, forward="entity", source=source)
    return Incoming(drop=f"kind 不认识：{kind}", source=source)


def from_public_fixes(payload: dict, book: str, hidden: set[str] = frozenset()) -> list[Incoming]:
    """网站公开实时读 ``/api/fixes?book=&volume=`` 的 ``volumes``（公开形：``who`` 只有 voter 前 6 位，正文已脱敏）。
    中心库 fixes.jsonl 还没同步到的新意见从这里进；来源键与 KV 那份相同，日后同步进来不会重复入池。"""
    out = []
    if payload.get("book") not in (None, book):
        return out
    for vol, items in (payload.get("volumes") or {}).items():
        for it in items or []:
            kind, at, end, sub, who = it.get("kind"), it.get("at"), it.get("end") or "", it.get("sub") or "", it.get("who") or ""
            src = f"api/fixes?volume={vol}"
            if is_test(it):
                out.append(Incoming(drop="测试票", source=src))
                continue
            raw_id = f"{kind}~{at}~{end}~{sub}~{who}"
            rec = {"kind": kind, "book_id": book, "volume": vol, "voter": who, "ts": it.get("ts")}
            if kind == "char":
                rec.update(text_version=it.get("tv"), cell_id=at, old_char=it.get("old"), new_char=it.get("new"), basis=it.get("note"))
                if it.get("fig"):
                    rec.update(figure=True, alt=it.get("alt"))
            elif kind == "span":
                rec.update(text_version=it.get("tv"), start=at, end=end, sub=sub or "other", old_text=it.get("old"),
                           new_text=it.get("new"), note=it.get("note"))
            else:
                rec.update(entity_id=it.get("eid"), entity_version=it.get("ev"), anchor={"start": at, "end": end},
                           text=it.get("old"), note=it.get("note"))
            inc = from_fix_record(rec, book, hidden, source=src)
            if inc.op:
                inc.op.raw_id = raw_id
            out.append(inc)
    return out


# ---- 精校票 ----

def from_cellreview(r: dict, book: str, source: str = "") -> Incoming:
    """中心库 ``<rev>.jsonl`` 的一行（``{v, book, vol, a, rev, choice, char, note, shown, voter, iph, ts}``）。"""
    if r.get("book") != book:
        return Incoming(drop="不是本书", source=source)
    if is_test(r):
        return Incoming(drop="测试票", source=source)
    a, rev, choice, voter = r.get("a"), r.get("rev") or "", r.get("choice"), r.get("voter") or ""
    if not a or choice not in CHOICE_CATEGORY:
        return Incoming(drop="格位或 choice 不认识", source=source)
    if choice == "char" and len(r.get("char") or "") != 1:
        return Incoming(drop="char 档要单个字", source=source)
    v3 = vol3(rev.split("-r")[0]) or vol3(r.get("vol"))
    prop = {"choice": choice, **({"text": r["char"]} if r.get("char") and choice != "figure" else {}),
            **({"alt": r["alt"]} if choice == "figure" and r.get("alt") else {})}
    extra = {k: r[k] for k in ("shown", "pick_src", "pick_rank", "pivot") if r.get(k) not in (None, "")}
    op = _op("cellreview", book, v3, f"cr:{rev}:{book}:{a}|{voter[:6]}", f"cr:{rev}:{book}:{a}", voter, r.get("ts"),
             {"start": a, "end": a, "rev": rev, **({"check": r["shown"]} if r.get("shown") else {})},
             CHOICE_CATEGORY[choice], prop, r.get("note"), extra)
    return Incoming(op=op, source=source)


# ---- 通用反馈 ----

def feedback_text_class(rec: dict) -> bool:
    """文字类：``category=typo``，或页面在 ``/read/`` 下（设计第三节）。"""
    path = urllib.parse.urlparse(rec.get("pageUrl") or "").path
    return rec.get("category") == "typo" or path.startswith("/read/")


def feedback_book_vol(rec: dict) -> tuple[str, str]:
    """``/read/<书>/<章>`` → (书, 章三位)；条目页 ``resourceId`` 当书。"""
    path = urllib.parse.urlparse(rec.get("pageUrl") or "").path
    m = re.match(r"^/read/([0-9a-z]+)(?:/([^/#?]+))?", path)
    if m:
        return m.group(1), vol3(m.group(2)) if m.group(2) else ""
    return rec.get("resourceId") or "", ""


def from_feedback(rec: dict, book: str) -> Incoming:
    rid = rec.get("id") or ""
    if not rid.startswith("fb_"):
        return Incoming(drop="不是 fb_ 记录", source="api/feedback")
    if is_test(rec) or rec.get("visibility") == "hidden":
        return Incoming(drop="测试或隐藏", source="api/feedback")
    if not feedback_text_class(rec):
        return Incoming(drop="非文字类", source="api/feedback")
    b, v = feedback_book_vol(rec)
    if b != book:
        return Incoming(drop="不是本书", source="api/feedback")
    extra = {k: rec[k] for k in ("type", "category", "subtype", "pageUrl", "status") if rec.get(k)}
    op = _op("feedback", book, v, f"fb:{rid}", rid, None, rec.get("createdAt") or "", {}, "other", None,
             rec.get("content"), extra)
    return Incoming(op=op, pending_normalize=True, raw=rec, source="api/feedback")


# ---- 取数 ----

def _get_json(url: str, timeout: float = 30):
    req = urllib.request.Request(url, headers={"user-agent": "open-guji-cv-opinions"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def fetch_public_feedback(site: str = SITE, limit: int = 100, pages: int = 50) -> list[dict]:
    items, cursor = [], ""
    for _ in range(pages):
        q = {"limit": limit, **({"cursor": cursor} if cursor else {})}
        d = _get_json(f"{site}/api/feedback?" + urllib.parse.urlencode(q))
        items += d.get("items") or []
        cursor = d.get("cursor") or ""
        if not d.get("hasMore") or not cursor:
            break
    return items


def fetch_public_fixes(book: str, vols: list[str], site: str = SITE) -> list[dict]:
    out = []
    for v in vols:
        d = _get_json(f"{site}/api/fixes?" + urllib.parse.urlencode({"book": book, "volume": v}))
        if d.get("success"):
            out.append(d)
    return out


@dataclass
class Sources:
    """一次入池读到的原始材料（都可以离线给，测试就这么做）。"""
    fixes: list[dict] = field(default_factory=list)            # fixes.jsonl 的行
    cellreview: dict[str, list[dict]] = field(default_factory=dict)   # 文件名 → 行
    public_fixes: list[dict] = field(default_factory=list)     # /api/fixes 回包
    feedback: list[dict] = field(default_factory=list)         # /api/feedback items
    hidden: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)


def _jsonl(text: str) -> list[dict]:
    return [json.loads(x) for x in (text or "").splitlines() if x.strip()]


def read_central_web(worker, ws: str, book: str, branch: str = "main") -> Sources:
    """中心库 ``feedback/lists/web/<书>/``：fixes.jsonl、<rev>.jsonl、hidden.txt（只读）。"""
    q = {"branch": branch, "ws": ws}
    prefix = f"feedback/lists/web/{book}/"
    files = worker._call("GET", "/v1/files", query={**q, "prefix": prefix}).get("files") or []
    src = Sources()
    for f in files:
        name = f["src_path"][len(prefix):]
        if name not in ("fixes.jsonl", "hidden.txt") and not REV_FILE_RE.match(name):
            continue
        text = worker._call("GET", "/v1/files", query={**q, "src_path": f["src_path"]}).get("text") or ""
        if name == "fixes.jsonl":
            src.fixes = _jsonl(text)
        elif name == "hidden.txt":
            src.hidden = parse_hidden(text)
        else:
            src.cellreview[name] = _jsonl(text)
        src.notes.append(f"中心库 {f['src_path']}（{f.get('bytes')} 字节，rev {f.get('rev')}）")
    if not any(f["src_path"].endswith("/fixes.jsonl") for f in files):
        src.notes.append(f"中心库没有 {prefix}fixes.jsonl（网站 Action 还没同步过改字意见）")
    return src


def read_dir(d: Path) -> Sources:
    """离线目录：``fixes.jsonl``、``<rev>.jsonl``、``hidden.txt``、``api-fixes*.json``、``api-feedback*.json``。"""
    d = Path(d)
    src = Sources()
    if (d / "fixes.jsonl").is_file():
        src.fixes = _jsonl((d / "fixes.jsonl").read_text(encoding="utf-8"))
    if (d / "hidden.txt").is_file():
        src.hidden = parse_hidden((d / "hidden.txt").read_text(encoding="utf-8"))
    for p in sorted(d.iterdir()):
        if REV_FILE_RE.match(p.name):
            src.cellreview[p.name] = _jsonl(p.read_text(encoding="utf-8"))
        elif p.name.startswith("api-fixes") and p.suffix == ".json":
            src.public_fixes.append(json.loads(p.read_text(encoding="utf-8")))
        elif p.name.startswith("api-feedback") and p.suffix == ".json":
            j = json.loads(p.read_text(encoding="utf-8"))
            src.feedback += j.get("items", j) if isinstance(j, dict) else j
    return src


def incoming(src: Sources, book: str) -> list[Incoming]:
    out = [from_fix_record(r, book, src.hidden) for r in src.fixes]
    for name, rows in sorted(src.cellreview.items()):
        out += [from_cellreview(r, book, source=name) for r in rows]
    for p in src.public_fixes:
        out += from_public_fixes(p, book, src.hidden)
    out += [from_feedback(r, book) for r in src.feedback]
    return out


# ---- 入池 ----

def _content(op: Opinion) -> tuple:
    """同 id 比内容：时间、位置、类别、建议、原话（voter、raw_id、extra 因来源不同而不同，不比）。"""
    t = {k: v for k, v in (op.target or {}).items()}
    return (op.ts, json.dumps(t, sort_keys=True, ensure_ascii=False), op.category,
            json.dumps(op.proposal or {}, sort_keys=True, ensure_ascii=False), op.note or "")


def dup_key(op: Opinion) -> tuple | None:
    t = op.target or {}
    if op.channel == "feedback" or not t.get("start"):
        return None
    ver = t.get("text_version") or t.get("rev") or t.get("entity_version") or ""
    return (op.vol, t["start"], t["end"], ver, op.category,
            json.dumps(op.proposal or {}, sort_keys=True, ensure_ascii=False))


@dataclass
class Report:
    added: list[str] = field(default_factory=list)
    existing: int = 0
    superseded: list[tuple[str, str]] = field(default_factory=list)
    forwarded: list[str] = field(default_factory=list)
    dup: list[tuple[str, str]] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)
    raw_merged: int = 0

    def summary(self) -> str:
        d = "、".join(f"{k} {v}" for k, v in sorted(self.dropped.items())) or "无"
        return (f"新入池 {len(self.added)} 条（其中转出 {len(self.forwarded)}、重复 {len(self.dup)}、"
                f"取代旧条 {len(self.superseded)}）；已在池里 {self.existing} 条；不入池：{d}；通用反馈存档 {self.raw_merged} 条")


def ingest(store: OpinionStore, items: list[Incoming], by: str = "ingest") -> Report:
    """把规整好的记录放进池里（只改内存，调用方 ``store.save()``）。重跑新增 0。"""
    rep = Report()
    for inc in items:
        if inc.raw is not None and store.merge_raw(inc.raw):
            rep.raw_merged += 1
        if inc.op is None:
            rep.dropped[inc.drop or "?"] = rep.dropped.get(inc.drop or "?", 0) + 1
            continue
        op = inc.op
        base = op.id
        chain = [i for i in store.opinions if i == base or i.startswith(base + "_")]
        if chain:
            if any(_content(store.opinions[i]) == _content(op) for i in chain):
                rep.existing += 1
                continue
            # 同一来源改了意见（网站同 key 覆盖）：追加新 id，旧的记 superseded
            n = 2
            while f"{base}_{n}" in store.opinions:
                n += 1
            op.id = f"{base}_{n}"
            old = sorted(chain, key=lambda i: store.opinions[i].ts)[-1]
        else:
            old = None
        data = {"source": inc.source, **({"pending_normalize": True} if inc.pending_normalize else {})}
        store.add(op, log_data=data)
        rep.added.append(op.id)
        if old:
            store.log(old, "superseded", {"by": op.id, "reason": "同一来源改了意见"}, by=by)
            rep.superseded.append((old, op.id))
        if inc.forward:
            store.log(op.id, "forwarded", {"to": inc.forward}, by=by)
            rep.forwarded.append(op.id)
    rep.dup = mark_dups(store, set(rep.added), by=by)
    return rep


def mark_dups(store: OpinionStore, new_ids: set[str], by: str = "ingest") -> list[tuple[str, str]]:
    """同章、同格、同版本、同类别、同建议、不同来源：最早那条为本，后来的（本次新入池的）记 ``dup``。"""
    st = store.statuses()
    groups: dict[tuple, list[Opinion]] = {}
    for op in store.opinions.values():
        if st.get(op.id) in ("superseded", "forwarded") and op.id not in new_ids:
            continue
        k = dup_key(op)
        if k:
            groups.setdefault(k, []).append(op)
    out = []
    for ops in groups.values():
        if len(ops) < 2:
            continue
        ops.sort(key=lambda o: (o.ts, o.id))
        root = ops[0]
        seen = {(root.voter or "")[:6]}
        for o in ops[1:]:
            w = (o.voter or "")[:6]
            if o.id in new_ids and st.get(o.id) != "dup" and w not in seen:
                store.log(o.id, "dup", {"of": root.id}, by=by)
                out.append((o.id, root.id))
            seen.add(w)
    return out


def describe(op: Opinion) -> str:
    t = op.target or {}
    loc = (t.get("start") or "") + (f"–{t['end']}" if t.get("end") and t.get("end") != t.get("start") else "")
    ver = t.get("text_version") or t.get("rev") or ""
    prop = op.proposal or {}
    p = (prop.get("choice", "") + ("=" if prop.get("choice") and prop.get("text") else "") + prop.get("text", "")) or "—"
    return (f"{op.id}  {op.channel:<10} {op.vol or '—'} {loc or '—'} @{ver or '—'}  {op.category:<7} "
            f"{(t.get('check') or '')!s}→{p}  {(op.note or '')[:40]}")


def sort_key(op: Opinion):
    t = op.target or {}
    return (op.vol or "", cell_key(t["start"]) if t.get("start") else (0, 0, 0, ""), op.ts, op.id)


__all__ = [
    "Incoming",
    "Report",
    "Sources",
    "desensitize",
    "fetch_public_feedback",
    "fetch_public_fixes",
    "from_cellreview",
    "from_feedback",
    "from_fix_record",
    "from_public_fixes",
    "incoming",
    "ingest",
    "is_test",
    "now_iso",
    "read_central_web",
    "read_dir",
]
