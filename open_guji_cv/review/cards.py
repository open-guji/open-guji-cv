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

from pathlib import Path

from ..core.book import load_book
from ..core.spec import cell_key, page_key
from ..gold.v2_align import align_book
from ..products.store import ProductStore
from ..variant_ledger import BookLedger


def cards(book: str, pages: str = "dev_set", limit: int = 400,
          only: str = "review", store: ProductStore | None = None) -> dict:
    """待审卡片：一格一张，带图块 URL、库/OCR/上下文三路证据与疑问。

    `only`：review = 只出人审的（默认）；auto = 只出自动进库的（抽查用）；
    all = 全出。**抽查自动档是必要的**——只看人审那批，永远只能证明
    「拿不准的我确实拿不准」，证不出自动那批有没有错（那正是 100% 准确率
    这个数字要防的自证）。
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
    # 第二意见：维基文库版整理本（2026-09-07）。两本人裁位上互不同的 164 处，现有整理本对 75、
    # 维基对 8——整体信现有整理本，但维基能抓到它的几处真错（搏/摶、始/姑、棺/輨、會/曾）。
    # 两本字不同时卡片并排给出，不改任何自动通道。
    golds2: dict = {}
    wiki = Path("corpus/zongmu_wikisource_reference.txt")
    if wiki.exists():
        try:
            golds2 = {c.id: c for g in align_book(book, pgs, st, corpus_path=wiki)
                      if g.anchored for c in g.chars}
        except Exception:
            golds2 = {}
    ledger = BookLedger.load_or_empty()
    out: list[dict] = []
    for pg in pgs:
        a = st.read(book, "admit_decide", page_key(pg), "admit_decide")
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
                mr, dr = mm.get(r.id), dd.get(r.id)
                key = cell_key(pg, cc.col, r.slot) + (r.sub or "")
                gc = golds.get(r.id)
                ref = None
                if gc and gc.reading:
                    pf = ledger.preferred_form(gc.reading)
                    gc2 = golds2.get(r.id)
                    ref = {"char": gc.reading, "op": gc.align_op, "run": gc.op_run,
                           "form": pf if pf and pf != gc.reading else None,
                           # 维基版在这一位印的字，只在与现有整理本不同时给
                           "wiki": (gc2.reading if gc2 and gc2.reading and gc2.reading != gc.reading
                                    else None)}
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
                            "source": dr.source} if dr else None,
                })
                if len(out) >= limit:
                    return {"book": book, "cards": out, "truncated": True}
    return {"book": book, "cards": out, "truncated": False}
