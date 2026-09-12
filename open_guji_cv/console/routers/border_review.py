# -*- coding: utf-8 -*-
"""控制台 · 边框类裁决（Step1 列探测/抬头/外框外延，Step2 上下版框核校）。

用户 2026-09-11 定：「以后完全不走 artifact，都走控制台」。原先靠
`scripts/build_border_gold_reviews.py` / `build_column_border_review.py`
生成一次性 Artifact 网页裁决，标完脚本导出金标。这四条路由把同一套裁决
搬进控制台：卡片列表 + 图像 + 裁决回读；提交裁决走已有的 `/api/events`
（不新增端点，前端直接调 `postEvents`）。

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `review/border_cards.py`。
"""
from __future__ import annotations

import cv2
from fastapi import APIRouter, HTTPException, Response

import numpy as np

from .. import deps
from ..errors import maps_http
from ...core.book import load_book
from ...core.step import RunContext
from ...review import border_cards as bc

router = APIRouter()

_CARD_BUILDERS = {
    "cols": bc.cols_cards,
    "head": bc.head_cards,
    "outer": bc.outer_cards,
    "colborder": bc.colborder_cards,
    "linebot": bc.colborder_line_cards,
    "pageline": bc.page_bottom_cards,
}


@router.get("/api/border-review/cards")
def api_border_review_cards(book: str, kind: str, pages: str = "dev_set") -> dict:
    """六类之一的卡片列表。`kind`：cols / head / outer / colborder / linebot / pageline。"""
    build = _CARD_BUILDERS.get(kind)
    if build is None:
        raise HTTPException(404, f"没有这一类裁决卡：{kind}")
    bk = load_book(book)
    pg = bk.resolve_pages(pages)
    cards = build(deps.product_store(), book, pg)
    return {"book": book, "kind": kind, "pages": pg, "n": len(cards), "cards": cards}


@router.get("/api/border-review/verdicts")
def api_border_review_verdicts(batch: str) -> dict:
    """读回某批次已裁的边框类卡片——刷新页面不该重审一遍（同 id 后到覆盖）。

    `border_line`（linebot 坐标金标）额外带 `y`；`border_offset`（pageline
    整页坐标金标）额外带 `y_left`/`y_right`（两端点各自坐标，不是单一
    偏移量——现役斜率本身也可能探错，见 `page_bottom_cards` 模块头）——
    没有它们前端就没法在刷新后把线画回人上次拖定的位置，只剩一个"已裁"
    的空壳。
    """
    log = deps.event_log()
    out: dict[str, dict] = {}
    for e in sorted(log.read(batch), key=lambda x: (x.batch, x.seq)):
        if e.kind not in ("verdict", "border_class", "border_line", "border_offset"):
            continue
        if e.kind == "border_line":
            v = e.payload.get("verdict")
            if v is None:
                continue
            out[e.target.key] = {"verdict": v, "y": e.payload.get("y")}
            continue
        if e.kind == "border_offset":
            v = e.payload.get("verdict")
            if v is None:
                continue
            out[e.target.key] = {"verdict": v, "y_left": e.payload.get("y_left"),
                                  "y_right": e.payload.get("y_right")}
            continue
        v = e.payload.get("verdict") or e.payload.get("border_class")
        if v is None:
            continue
        out[e.target.key] = {"verdict": v}
    return {"batch": batch, "n": len(out), "verdicts": out}


def _encode(img, q: int = 82) -> Response:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    if not ok:
        raise HTTPException(500, "编码失败")
    return Response(content=buf.tobytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


@router.get("/api/border-review/img/{book}/{page}.jpg")
@maps_http
def api_border_review_img(book: str, page: int, kind: str, side: str = "top",
                          col: int = 0, w: int = 560) -> Response:
    """四类卡片各自的图。**不缓存**——画的是产物，重跑一步就变了（同
    `products.py::_png` 的教训：2026-09-10 缓存过一次「重跑完还是旧图」）。
    """
    st = deps.product_store()
    if kind == "cols":
        return _encode(bc.render_cols_img(st, book, page, page_w=w))
    if kind == "head":
        return _encode(bc.render_head_img(st, book, page))
    if kind == "outer":
        return _encode(bc.render_outer_img(st, book, page, side))
    if kind == "colborder":
        b = load_book(book)
        ctx = RunContext(b, st, deps.image_cache(), log=lambda s: None)
        crop, prof = bc.render_colborder_img(ctx, book, page, col, side)
        # 投影曲线随图一起画在右侧，避免前端再单独拉一个数据端点
        h, _cw = crop.shape
        strip = np.zeros((h, 48), dtype=np.uint8)
        pmax = max(max(prof) if prof else 0.0, 0.02)
        for y, v in enumerate(prof):
            x = int(v / pmax * 47)
            strip[y, :max(1, x)] = 255
        out = cv2.cvtColor(np.concatenate([crop, np.full((h, 4), 200, dtype=np.uint8), strip], axis=1),
                           cv2.COLOR_GRAY2BGR)
        return _encode(out)
    if kind == "pageline":
        return _encode(bc.render_pageline_img(st, book, page), q=88)
    raise HTTPException(404, f"没有这一类图：{kind}")
