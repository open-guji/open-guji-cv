# -*- coding: utf-8 -*-
"""定字待审卡片的装配：一格一张，带图块 URL 与库/OCR/上下文三路证据。

从 `console/app.py::api_review_cards` 搬来（控制台重构 C2）。**装配逻辑一行未改**，
只动了三处：函数名、`ProductStore` 改成可注入、三个函数内的延迟 import 提到模块级。

搬出来之后**云端道也能调它**——不是为了显示卡片，是为了
「统计还剩多少待审、抽查自动放行那批、量一刀改动前后的待审率变化」
（方案 §二·第六类：这十条接口没有一条需要人在场，需要人在场的是浏览器里那个页面）。

⚠️ `patch` 字段仍然是 `/api/cache/...` 这种**控制台 URL**。它是给前端用的，
CLI 只看 `id`/`char`/`doubts` 那几列就行；换成别的形状会动到前端，不在本轮。
"""
from __future__ import annotations

from ..core.book import load_book
from ..core.spec import cell_key, page_key
from ..gold.v2_align import align_book
from ..products.store import ProductStore
from ..variant_ledger import BookLedger


def cards(book: str, pages: str = "dev_set", limit: int = 400,
          only: str = "review", store: ProductStore | None = None,
          gate_cut: bool = True) -> dict:
    """待审卡片：一格一张，带图块 URL、库/OCR/上下文三路证据与疑问。

    `only`：review = 只出人审的（默认）；auto = 只出自动进库的（抽查用）；
    all = 全出。**抽查自动档是必要的**——只看人审那批，永远只能证明
    「拿不准的我确实拿不准」，证不出自动那批有没有错（那正是 100% 准确率
    这个数字要防的自证）。

    `gate_cut`：顺序闸（用户 2026-09-10）——切分线还没 review 的格位先不出字卡。
    被挡下的进返回值的 `blocked`，面板据此显示「还有 N 位等着先看切线」。
    默认开；传 False 可整批看全部（判据 E 抽审、跑评测要用）。
    """
    st = store or ProductStore()
    bk = load_book(book)
    pgs = bk.resolve_pages(pages)
    # 整理本对应字：用户 2026-09-06「审阅时没看到整理本用的是什么，应该放第一位」。
    # 拿 v2_align 的页对齐（`reading` = 整理本在这一位印的字），锚不上的页没有。
    # 忠于刻本字形：整理本印 即、本书惯刻 卽 时，账本的 preferred 也一并给，卡片并排列出。
    try:
        golds = {c.id: c for g in align_book(book, pgs, st) if g.anchored for c in g.chars}
    except Exception:
        golds = {}
    ledger = BookLedger.load_or_empty()
    out: list[dict] = []
    out_blocked: list[dict] = []
    blocked = cut_pending(book, pgs, st) if gate_cut else {}
    for pg in pgs:
        a = st.read(book, "seed_admit", page_key(pg), "seed_admit")
        m = st.read(book, "glyph_match", page_key(pg), "glyph_match")
        d = st.read(book, "context_decide", page_key(pg), "context_decision")
        if a is None:
            continue
        mm = {r.id: r for cc in (m.columns if m else []) for r in cc.chars}
        dd = {r.id: r for cc in (d.columns if d else []) for r in cc.chars}
        for cc in a.columns:
            if not cc.ok:
                continue
            for r in cc.chars:
                if only == "review" and r.admit:
                    continue
                if only == "auto" and not r.admit:
                    continue
                # 顺序闸（用户 2026-09-10 定）：这一位旁边有一条**还没 review 的切线**时，
                # 先别出字卡——先把切分线看过，再来看这个字。粒度是格位，不整页挡。
                _pend = blocked.get((pg, cc.col, r.slot))
                if _pend is not None:
                    out_blocked.append({"id": r.id, "page": pg, "col": cc.col,
                                        "slot": r.slot, "pending": _pend})
                    continue
                mr, dr = mm.get(r.id), dd.get(r.id)
                key = cell_key(pg, cc.col, r.slot) + (r.sub or "")
                gc = golds.get(r.id)
                ref = None
                if gc and gc.reading:
                    pf = ledger.preferred_form(gc.reading)
                    ref = {"char": gc.reading, "op": gc.align_op, "run": gc.op_run,
                           "form": pf if pf and pf != gc.reading else None}
                out.append({
                    "id": r.id, "page": pg, "col": cc.col, "slot": r.slot, "sub": r.sub or "",
                    "patch": f"/api/cache/{book}/char_patch/{key}.png",
                    "admit": r.admit, "channel": r.channel, "char": r.char,
                    "reading": r.reading,
                    # 整理本在这一位印的字（页对齐给的）；form = 本书惯刻的形（账本 preferred，≠整理本字时才有）
                    "ref": ref,
                    # 「义定形未定」的组内候选与三源证据（variant_form），卡片按它只列组内形
                    "form": (r.evidence or {}).get("form"),
                    "doubts": r.doubts,
                    "db": {"verdict": mr.verdict, "cov": round(mr.cov, 4),
                           "wmax": round(mr.wmax, 1),
                           "candidates": mr.candidates[:5]} if mr else None,
                    "ocr": (r.evidence or {}).get("ocr", []),
                    "ctx": {"char": dr.char, "margin": dr.margin,
                            "source": dr.source,
                            "llm_suggestion": dr.llm_suggestion} if dr else None,
                })
                if len(out) >= limit:
                    return {"book": book, "cards": out, "truncated": True,
                            "blocked": out_blocked}
    return {"book": book, "cards": out, "truncated": False, "blocked": out_blocked}


def blocking_cutline_cases(book: str, pgs: list[int], st: ProductStore) -> list[dict]:
    """顺序闸正在挡住字卡的那批切线用例（原始 case，未展开成格位字典）。

    **只挡多候选的切点**（用户定「只挡多候选切点」）：算法自己拿不准
    （给了 2+ 种切法）的地方才要人先看，单一候选说明算法有把握，不拦。

    ⚠️⚠️ **数据源必须与切线面板用的那批用例逐条相同**，否则闸门会挡下一张
    **面板根本出不了卡**的切点——人被告知「先去切线」，去了却找不到那条。
    实测踩过两次：

    1. 先拿 `eval.touching.r2s_boundaries` 当数据源 → 在 34 张待审卡上命中 **0**。
       r2s 只收「切点有墨、附近无墨谷」的真粘连，而待审字位上的 char/char 切点
       墨量多为 0，投影法本就解得开，压根不进 r2s。
    2. 改成直接读产物「有 2+ 候选就挡」 → 挡住 52 条，与面板能出的 729 条用例
       **交集为 0**。产物里的多候选按 `cut_candidates` 记，面板的用例另有
       「切点有墨 + 附近无墨谷 + 上下都是 char」的过滤，两者不是一回事。

    所以这里调**面板自己那个函数**取用例（r2s + split_char）。面板将来换了
    挑用例的口径，这里跟着变，不会再错位。被 `cut_pending`（按格位展开给
    定字审查用）与 Step7「切分裁决」板块（`scope=blocking` 时直接要这批
    完整 case 拖切线）两处共用。
    """
    from ..console import deps
    from ..eval import touching as T

    try:
        cases = (T.r2s_boundaries(book, pgs, st)
                 + T.split_char_boundaries(book, pgs, st))
    except Exception:
        return []   # 取不到用例（无产物/无金标）就当没有闸，不挡人

    done = T.gold_ids()
    try:
        for e in deps.event_log().read():
            if e.kind == "cutline":
                done.add(e.target.key)
    except Exception:
        pass    # 没有事件日志（新工作区）不该让整个审查面板挂掉

    # 产物里哪些切点是多候选的（key = (页, 列, 上格格位) → 候选条数）
    multi: dict = {}
    for pg in pgs:
        cells = st.read(book, "row_segment", page_key(pg), "cells")
        if cells is None:
            continue
        for cc in cells.columns:
            for cp in (getattr(cc, "cut_candidates", None) or []):
                if len(cp.candidates) >= 2:
                    multi[(pg, cc.col, cp.slot_above)] = len(cp.candidates)

    out = []
    for c in cases:                     # 只走面板真能出卡的那些
        if c["id"] in done:
            continue                    # 已经 review 过了
        n = multi.get((c["page"], c["col"], c["slot_above"]))
        if not n:                       # 单一候选 = 算法有把握，不拦
            continue
        c = {**c, "n_candidates": n}    # 挂候选条数，供 cut_pending 拼说明
        out.append(c)
    return out


def cut_pending(book: str, pgs: list[int], st: ProductStore) -> dict:
    """还等着 review 的切线，按格位索引：`(页, 列, 格位) → 说明`。

    **判据（用户 2026-09-10 定：按「格位」挡）**：一条切线的**上格与下格**都是
    被它切出来的字位——切法改了，这两个字的图块就跟着变。所以这两格的字卡在
    切线 review 完之前不出来，其余格位照常。数据源见 `blocking_cutline_cases`。
    """
    cases = blocking_cutline_cases(book, pgs, st)
    out: dict = {}
    for c in cases:
        why = f"格线 {c['col']}:{c['bi']} 有 {c['n_candidates']} 种切法待 review"
        # 上格与下格都是被这条切线切出来的字位，两张卡一起挡
        out[(c["page"], c["col"], c["slot_above"])] = why
        out[(c["page"], c["col"], c["slot_below"])] = why
    return out
