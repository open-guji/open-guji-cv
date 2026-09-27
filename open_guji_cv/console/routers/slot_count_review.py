# -*- coding: utf-8 -*-
"""Step3 逐列字数人裁台：卡片列表 + 图像 + 裁决回读。

领域逻辑在 `review/slot_count_cards.py`（为什么要这个环节、出卡范围、裁决怎么
用，见那边的模块 docstring）。这里只做「解析参数 → 调库 → 返回」，跟
`border_review.py`/`column_review.py` 同一分工。

裁决走既有事件链路（`POST /api/events`），`kind="n_body_slots"`，路由表新增
一条到 `char-segmentation/column-slots` 分片 + `product_invalidate`（见
`feedback/routes.py`）。
"""
from __future__ import annotations

import cv2
from fastapi import APIRouter, Depends, HTTPException, Response

from ...core.spec import page_key
from ...review.slot_count_cards import render_slot_count_img, slot_count_cards
from .. import deps
from ..auth import require_reviewer

router = APIRouter(dependencies=[Depends(require_reviewer)])


@router.get("/api/slot-count-review/cards")
def api_slot_count_cards(book: str, pages: str = "dev_set") -> dict:
    from ...core.book import load_book
    st = deps.product_store()
    bk = load_book(book)
    pgs = bk.resolve_pages(pages)
    cards = slot_count_cards(st, book, pgs)
    return {"book": book, "pages": pgs, "n": len(cards), "cards": cards}


@router.get("/api/slot-count-review/verdicts")
def api_slot_count_verdicts(batch: str) -> dict:
    """读回本批已裁的列（刷新不重做；同 id 后到覆盖）。"""
    out: dict[str, dict] = {}
    try:
        for e in deps.event_log().read(batch):
            if e.kind != "n_body_slots":
                continue
            key = (e.target.key if e.target else None) or ""
            if not key:
                continue
            pay = e.payload or {}
            n = pay.get("n_slots")
            if n is not None:
                # `uniform` 缺省 True：2026-09-20 之前的裁决没有这个键，等距是
                # 版式常识，不能因为加了新键就把历史裁决的含义改掉。
                uni = pay.get("uniform")
                out[key] = {"n_slots": n, "uniform": True if uni is None else bool(uni)}
    except FileNotFoundError:
        pass
    return {"verdicts": out}


@router.get("/api/slot-count-review/img/{book}/{page}/{col}.png")
def api_slot_count_img(book: str, page: int, col: int) -> Response:
    try:
        im = render_slot_count_img(book, page, col, image_cache=deps.image_cache(),
                                   store=deps.product_store())
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    ok, buf = cv2.imencode(".png", im)
    if not ok:
        raise HTTPException(500, "编码失败")
    return Response(content=buf.tobytes(), media_type="image/png")
