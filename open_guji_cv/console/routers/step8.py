# -*- coding: utf-8 -*-
"""控制台 · Step8 对勘与复核。

设计见 `overview` 仓 `项目进展/图片初步数字化/进度/Step8-落库反馈/
04-扩为对勘与复核中枢-设计.md` 与 `05-差异三层分类与复核裁决台UI.md`。

Step8 原本只有三个落库出口，而那三件事**全在 Step7 的裁决提交里顺手做掉了**
（人点一下，事件写入、路由、落库一气呵成）。真正缺位置的是**全局复核**：
Step7 只知道「机器确不确定」，不知道「机器对不对」——后者只有与独立校对本
逐字对勘能答，而那是整册级的活，Step7 的页级契约装不下。

## 读已有产物，不现跑

对勘一次 ~100 s，不能每次开页面都跑。这里只读 `reports/<book>/` 下最新那份
JSON；要重跑走 `guji collate`（或前端的「重新对勘」按钮，走 `/api/step8/collate`）。

**不进管线**：同 Step9，整册级不满足 `run_page(ctx, page)` 契约。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ... import feedback as _fb  # noqa: F401  确保事件/路由模块已加载
from ...core.workspace import reports_root
from .. import deps
from ..auth import require_reviewer
from ..errors import maps_http
from ...feedback.anchor import enrich_events as _anchor_events

router = APIRouter(dependencies=[Depends(require_reviewer)])


def _latest(book: str) -> Path | None:
    d = reports_root() / book
    files = sorted(d.glob("collation_*.json")) if d.exists() else []
    return files[-1] if files else None


def _load(book: str) -> dict:
    p = _latest(book)
    if p is None:
        return {}
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["_file"] = p.name
    return doc


def _book_conventions(book: str) -> dict:
    """`books/<id>.yaml` 的 `char_conventions` → `{(刻本形, 校对本形): kind}`。"""
    try:
        from ...core.book import load_book
        rows = getattr(load_book(book), "char_conventions", None) or []
        return {tuple(r["pair"]): r.get("kind") or "" for r in rows if r.get("pair")}
    except Exception:
        return {}


def _jiajie() -> set:
    """`jiajie.tsv` → `{(刻本形, 校对本形)}`。人标过「这是通假」的字对。"""
    from ...report.tiers import JIAJIE_REL, load_pairs
    return load_pairs(JIAJIE_REL)


def _jiajie_of_book(book: str) -> set:
    """`jiajie.tsv` 里**本书复核批次**标的那些字对。`unmark_jiajie` 只撤得动这些：
    别的书标的行按它判「要不要撤」，每挪一次都会白写一条撤不掉的 unmark。"""
    from ...feedback.collate_consumers import jiajie_rows
    return {(a, b) for a, b, src in jiajie_rows() if src.startswith(f"human:evt_{book}-collate_")}


def _denied() -> set:
    """`variants.deny.tsv` → `{(刻本形, 校对本形)}`。人推翻过的关系图边。"""
    from ...feedback.collate_consumers import DENY_REL, _repo_path
    p = _repo_path(DENY_REL)
    out = set()
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                parts = ln.split("\t")
                if len(parts) >= 2:
                    out.add((parts[0], parts[1]))
    return out


_PAIR_CACHE: dict = {}


def _row_lookup(book: str) -> dict:
    """字位 id → 那条差异（字对＋上下文），查遍**全部**对勘报告（新的覆盖旧的）。

    旧的「校对本对」事件（2026-09-22～24）是 Step7 的 confirm，不带字对也不带上下文；
    改字后重跑，最新报告里这一格已经没有差异了，只有旧报告还记得它原来是哪一对、
    上下文是什么。查不到的话卡片上图和上下文都是空的（用户 2026-09-24 报「个别字无法显示图片」）。
    """
    d = reports_root() / book
    files = sorted(d.glob("collation_*.json")) if d.exists() else []
    sig = tuple((f.name, f.stat().st_mtime) for f in files)
    hit = _PAIR_CACHE.get(book)
    if hit and hit[0] == sig:
        return hit[1]
    out: dict = {}
    for f in files:
        for x in json.loads(f.read_text(encoding="utf-8")).get("diffs") or []:
            if x.get("id") and x.get("char") and x.get("ref"):
                out[x["id"]] = x
    _PAIR_CACHE[book] = (sig, out)
    return out


def _items(book: str, doc: dict) -> list[dict]:
    """最新对勘报告 ＋ 本书复核事件 → 逐字位的状态行（`collate_state.build_items`）。"""
    from ...feedback.collate_state import CONV_KIND_CAT, build_items, human_verdicts
    from ...report.tiers import tier_of
    conv = _book_conventions(book)
    conv_set, denied, jj = set(conv), _denied(), _jiajie()
    verdicts = human_verdicts(deps.event_log().read(f"{book}-collate"), book,
                              _row_lookup(book).get)
    return build_items(
        doc.get("diffs") or [], verdicts,
        lambda a, b, n: tier_of(a, b, n, conventions=conv_set, denied=denied, jiajie=jj),
        {p: CONV_KIND_CAT.get(k, "other") for p, k in conv.items()})


@router.get("/api/step8/overview/{book}")
@maps_http
def api_step8_overview(book: str) -> dict:
    """对勘结论 ＋ 校对本无此段。**不现跑**，读最新那份 JSON。

    各类的数在 `/api/step8/queue` 一并给，这里不重复算。
    """
    doc = _load(book)
    if not doc:
        return {"book": book, "has_report": False,
                "hint": "还没有对勘产物，点「重新对勘」或跑 `guji collate`"}
    diffs = doc.get("diffs") or []
    summary = doc.get("summary") or {}
    n_equal = sum(w.get("n_equal", 0) for w in (summary.get("by_witness") or {}).values())
    n_slots = sum(p.get("n_slots", 0) for p in
                  (w for pg in (doc.get("page_stats") or [])
                   for w in (pg.get("witnesses") or {}).values()))
    return {
        "book": book, "has_report": True, "file": doc.get("_file"),
        "built_at": doc.get("built_at"), "pages": doc.get("pages"),
        "n_slots": n_slots, "n_equal": n_equal,
        "unanchored": doc.get("unanchored"),
        "absent_runs": summary.get("absent_runs") or [],
        # 增删聚合不了（没有「对应的另一个字」），单独给个数
        "gaps": sum(1 for d in diffs if str(d.get("kind", "")).startswith(("missing", "extra"))),
    }


@router.get("/api/step8/queue/{book}")
@maps_http
def api_step8_queue(book: str, bucket: str = "pending", cat: str = "",
                    limit: int = 500) -> dict:
    """两层分类下某一类的卡片 ＋ 全部类的计数（2026-09-24）。

    `bucket` ∈ pending / ours / theirs / neither；`cat` 只在 ours 下有意义，空 = 全部。
    卡片 = 同一字对 × 同一状态的一组字位（**按对不按条**，𠊓→傍 一对占 24 条）。
    """
    from ...feedback.collate_state import counts, group_items
    doc = _load(book)
    items = _items(book, doc) if doc else []
    sel = [it for it in items
           if it["who"] == bucket and (bucket != "ours" or not cat or it["cat"] == cat)]
    all_groups = group_items(sel)
    n_groups = len(all_groups)
    groups = all_groups[:limit]
    seg = _seg_flags(book)
    for g in groups:
        for smp in g["samples"]:
            smp["seg"] = seg.get(smp["id"], [])
    return {"book": book, "has_report": bool(doc), "counts": counts(items),
            "groups": groups, "total": n_groups,
            "truncated": n_groups > limit}


_SEG_CACHE: dict = {}


def _seg_flags(book: str) -> dict:
    """人标过的切分缺陷（跨批次）。事件日志 ~1 MB，按各批次文件 mtime 缓存。"""
    from ...feedback.collate_state import seg_flags
    log = deps.event_log()
    d = log.events_dir
    sig = tuple(sorted((f.name, f.stat().st_mtime) for f in d.glob("*.jsonl"))) if d.exists() else ()
    hit = _SEG_CACHE.get(book)
    if hit and hit[0] == sig:
        return hit[1]
    out = seg_flags(log.iter_all(), book)
    _SEG_CACHE[book] = (sig, out)
    return out


class SegItem(BaseModel):
    id: str
    flags: list[str] = []


class SegIn(BaseModel):
    """切分反馈：每处勾了哪几项（全不勾 = 取消）。「N 处一起裁」时一次提交 N 处。"""

    book: str
    items: list[SegItem]


@router.post("/api/step8/seg")
@maps_http
def api_step8_seg(d: SegIn) -> dict:
    """卡片上图旁的「字形不完整 / 有噪声」复选框（2026-09-24）。

    与「谁对 / 哪一类」**独立**，不改字、不影响分类；每处写一条 `confirm(v=seg_defect)`
    走现成的切分缺陷通道，落 `char-segmentation/instances` 金标给 Step3 当反馈。
    状态没变的那几处不写。
    """
    from ...feedback.collate_state import SEG_FLAGS, seg_payload
    from ...feedback.consumers import route_and_consume
    from ...feedback.events import EventTarget, make_event
    from ...feedback.harvest import parse_card_id
    from ...feedback.routes import RouteTable

    bad = [it.id for it in d.items
           if not it.id.startswith(f"{d.book}:") or any(f not in SEG_FLAGS for f in it.flags)]
    if bad or not d.items:
        return {"ok": False, "error": f"flags 只能是 {'/'.join(SEG_FLAGS)}，id 要是本书字位（{bad[:1]}）"}
    have = _seg_flags(d.book)
    todo = [it for it in d.items if sorted(it.flags) != sorted(have.get(it.id, []))]
    if not todo:
        return {"ok": True, "appended": 0}
    batch = f"{d.book}-collate"
    log = deps.event_log()
    base = log.latest_seq(batch)
    evs = [make_event(batch, base + i + 1, "confirm",
                      EventTarget(step="step8_collate", unit="cell", key=it.id,
                                  **parse_card_id(it.id)),
                      seg_payload(it.flags), source_format="server")
           for i, it in enumerate(todo)]
    _anchor_events(evs)   # 人裁带锚：重切后靠它找回是哪个字（总览/15）
    log.append(evs)
    out = {"ok": True, "appended": len(evs)}
    try:
        route_and_consume(log, batch, RouteTable.load(log.root / "routes.yaml"),
                          deps.verdict_store())
    except Exception as exc:                       # noqa: BLE001
        out["consume_error"] = f"{type(exc).__name__}: {exc}"
    return out


class DecideIn(BaseModel):
    """一次复核裁决 = 把 `ids` 这几处**挪进**某一类。按字对提交。"""

    book: str
    pair: list[str]              # [刻本形, 校对本形]
    ids: list[str]               # 这次要挪的字位（一起裁 = 全部，否则只一个）
    who: str = ""                # ours | theirs | neither；空 = 退回待审
    cat: str = ""                # who=ours 时：variant | jiajie | taboo | other
    fix: str = ""                # who=neither 时人输入的正确字
    note: str = ""


_VS = re.compile("[\ufe00-\ufe0f\U000e0100-\U000e01ef]")


def _nchars(t: str) -> int:
    """字数，不算异体选择符：`葛󠄀`（葛 + VS17）是一个字、两个码位。"""
    return len(_VS.sub("", t))


def _check(d: DecideIn) -> str:
    from ...feedback.collate_state import CATS, WHO
    if not d.ids or len(d.pair) != 2 or not all(d.pair) or d.pair[0] == d.pair[1]:
        return "缺 pair 或 ids"
    if d.who and d.who not in WHO:
        return f"who 只能是 {'/'.join(WHO)} 或空"
    if d.who == "ours" and (d.cat or "other") not in CATS:
        return f"cat 只能是 {'/'.join(CATS)}"
    if d.who == "neither" and _nchars(d.fix.strip()) != 1:
        return "「都不对」要输入**一个**正确的字"
    return ""


#: **这里就是「点哪个按钮落到哪」的唯一真相源**，前端传的是语义 key，不是标签。
#:
#: 每个字位一条 `collate_verdict`（状态本身）。副作用各走现成通道：
#: - 这一格**最终的字变了**（我方字 ↔ 校对本字 ↔ 人输入的字，含挪回我方/退回待审）
#:   → 一条 `confirm`，走 Step7 的改字／入库／失效产物；没变就不写，不白白入库；
#: - 字对在本书**有无一处归通假**变了 → `mark_jiajie` / `unmark_jiajie`（跨书表）。
def _events_for(d: DecideIn, base_seq: int, batch: str, current: dict[str, dict],
                jiajie: set, jiajie_mine: set | None = None):
    """一条裁决 → 要写的事件列表。`current`：这个字对**现在**的逐字位状态行。

    `jiajie`：整张通假表（有了就不必再标）；`jiajie_mine`：其中本书标的（只有这些撤得动）。
    """
    jiajie_mine = jiajie if jiajie_mine is None else jiajie_mine
    from ...feedback.collate_state import VIA, final_char
    from ...feedback.events import EventTarget, make_event
    from ...feedback.harvest import parse_card_id

    out = []

    def add(kind: str, key: str, payload: dict):
        ids = parse_card_id(key)
        out.append(make_event(batch, base_seq + len(out) + 1, kind,
                              EventTarget(step="step8_collate", unit="cell", key=key,
                                          **ids),
                              payload, source_format="server"))

    pair = list(d.pair)
    who = d.who
    cat = (d.cat or "other") if who == "ours" else ""
    fix = d.fix.strip() if who == "neither" else ""
    new_final = final_char(pair, who, fix)
    for key in d.ids:
        cur = current.get(key) or {}
        ctx = {k: cur.get(k) for k in ("page", "col", "slot", "sub", "hyp_ctx", "ref_ctx")}
        add("collate_verdict", key, {"pair": pair, "who": who, "cat": cat, "fix": fix,
                                     "final": new_final, "ctx": ctx, "note": d.note})
        if new_final != cur.get("final", pair[0]):
            add("confirm", key, {"v": "confirm", "shape": new_final,
                                 "conversion": 0, "no_glyph_lib": False, "via": VIA,
                                 "pair": pair, "note": d.note or f"Step8 复核：{who or '退回待审'}"})

    # 通假是贴给字对的跨书标签：看挪完之后本书还有没有一处归通假。自动归进来的也算——
    # 它们正是靠这张表归进来的（旧 ② 层点「通假」只记字对、不落字位），撤了表它们就散了
    moved = set(d.ids)
    jj_after = (who == "ours" and cat == "jiajie") or any(
        it["who"] == "ours" and it["cat"] == "jiajie"
        for k, it in current.items() if k not in moved)
    if jj_after and tuple(pair) not in jiajie:
        add("mark_jiajie", d.ids[0], {"pair": pair, "via": VIA, "note": d.note})
    elif not jj_after and tuple(pair) in jiajie_mine:
        add("unmark_jiajie", d.ids[0], {"pair": pair, "book": d.book, "via": VIA})
    return out


@router.post("/api/step8/decide")
@maps_http
def api_step8_decide(d: DecideIn) -> dict:
    """写复核裁决事件并按路由消费。

    `batch` 固定为 `<book>-collate`：与定字裁决（`<book>-*-decide`）**分批次**，
    互不干扰——两者问的不是同一个问题，混在一个批次里台账也看不清。
    """
    from ...feedback.consumers import route_and_consume
    from ...feedback.routes import RouteTable

    err = _check(d)
    if err:
        return {"ok": False, "error": err}
    doc = _load(d.book)
    current = {it["id"]: it for it in (_items(d.book, doc) if doc else [])
               if list(it["pair"]) == list(d.pair)}
    bad = [k for k in d.ids if k not in current]
    if bad:
        # 前端拿的是旧队列（别处刚裁过、或重跑了对勘）：宁可让人刷新，不往错的格上写
        return {"ok": False, "error": f"{len(bad)} 处不在「{d.pair[0]}→{d.pair[1]}」里"
                                      f"（{bad[0]}…），请刷新"}
    batch = f"{d.book}-collate"
    log = deps.event_log()
    evs = _events_for(d, log.latest_seq(batch), batch, current, _jiajie(),
                      _jiajie_of_book(d.book))
    _anchor_events(evs)   # 人裁带锚：重切后靠它找回是哪个字（总览/15）
    n = log.append(evs)
    confirms = [e for e in evs if e.kind == "confirm"]
    out = {"ok": True, "appended": n, "batch": batch,
           "kinds": sorted({e.kind for e in evs}),
           "changed": len(confirms),
           "final": confirms[0].payload["shape"] if confirms else ""}
    try:
        table = RouteTable.load(log.root / "routes.yaml")
        res = route_and_consume(log, batch, table, deps.verdict_store())
        out["consumed"] = [{"consumer": x["consumer"], "added": x["added"],
                            "skipped": x["skipped"], "errors": x["errors"][:3]}
                           for x in res["results"] if x["events"]]
    except Exception as exc:                       # noqa: BLE001
        # 事件已落盘，消费失败不该让人以为裁决没保存——同 /api/events 的处理。
        out["consume_error"] = f"{type(exc).__name__}: {exc}"
    return out
