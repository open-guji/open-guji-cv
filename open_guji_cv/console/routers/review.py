# -*- coding: utf-8 -*-
"""控制台 · 定字审查。

待审卡片 / 裁决回读 / 一列的上下文

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

from fastapi import APIRouter

from .. import deps
from ...core.spec import page_key
from ...review.cards import cards
from ...review.verdict_view import review_verdicts

router = APIRouter()



# ── 定字审查（C2：审查搬进控制台，不再走外部 artifact）────────────────
#
# 用户 2026-09-04 定：「审查也放控制台。之前的审查页需要复用的话，也迁移到
# 控制台。」这一组 API 就是那件事的后端：待审卡片从 `seed_admit` 产物来，
# 裁决直接 POST /api/events（既有接口），再走既有的路由 → glyphdb_admit。
# **不新造协议**——事件信封、批次登记、路由表全部沿用。


@router.get("/api/review/cards")
def api_review_cards(book: str, pages: str = "dev_set", limit: int = 400,
                     only: str = "review") -> dict:
    """待审卡片：一格一张，带图块 URL、库/OCR/上下文三路证据与疑问。

    装配在 `review/cards.py`（C2 搬出去的，云端道与 CLI 直接能调）。
    """
    return cards(book, pages, limit, only, deps.product_store())



@router.get("/api/review/verdicts")
def api_review_verdicts(batch: str) -> dict:
    """读回某批次已经裁过的字位——**刷新页面不该重审一遍**。装配在 `review/verdict_view.py`。"""
    return review_verdicts(batch, deps.event_log())



@router.get("/api/review/column/{book}/{page}/{col}")
def api_review_column(book: str, page: int, col: int) -> dict:
    """一列的上下文：定字串 + 每格的 slot，供审查页显示「这个字在哪句话里」。

    单看一个裁紧图块判不出形近字——`confusable-context` 154 题实测，字形层
    top-1 只有 64.3%，而 n-gram 95.5%、大模型 98.7%。人也一样需要上下文。

    ## 空位要用库/OCR 兜底填上（2026-09-04 改）

    原先只印 Step6 的定字，弃权位一律「□」。可**待审的位恰恰全是弃权位**
    ——人看到的就是一串「□□□」，等于没有上下文，读文定字也就无从谈起。
    现在逐级兜底：定字 → 库 top1 → OCR top1，并逐位标出它是不是待审、
    以及字从哪来，前端据此把待审位高亮、把兜底字标灰。
    """
    st = deps.product_store()
    d = st.read(book, "context_decide", page_key(page), "context_decision")
    m = st.read(book, "glyph_match", page_key(page), "glyph_match")
    o = st.read(book, "ocr_candidates", page_key(page), "ocr_candidates")
    a = st.read(book, "seed_admit", page_key(page), "seed_admit")
    if d is None and m is None:
        return {"text": "", "slots": []}
    dm = {r.id: r for cc in (d.columns if d else []) for r in cc.chars}
    om = {r.id: r for cc in (o.columns if o else []) for r in cc.chars}
    am = {r.id: r for cc in (a.columns if a else []) for r in cc.chars}
    src_col = (m.column(col) if m else None) or (d.column(col) if d else None)
    if src_col is None:
        return {"text": "", "slots": []}
    out = []
    for r in sorted(src_col.chars, key=lambda x: (x.slot, x.sub or "")):
        dd, oo, aa = dm.get(r.id), om.get(r.id), am.get(r.id)
        ch, src = None, ""
        if dd is not None and dd.char:
            ch, src = dd.char, (dd.source or "context")
        elif getattr(r, "candidates", None):
            ch, src = r.candidates[0][0], "db"
        elif oo is not None and oo.topk:
            ch, src = oo.topk[0][0], "ocr"
        out.append({"slot": r.slot, "sub": r.sub, "id": r.id,
                    "char": ch, "source": src,
                    # 待审 = seed_admit 没放行；前端据此高亮
                    "review": bool(aa is not None and not aa.admit)})
    return {"text": "".join(x["char"] or "□" for x in out), "slots": out}
