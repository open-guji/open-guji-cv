# -*- coding: utf-8 -*-
"""控制台 · 产物与图像。

数值产物 / 清单 / 原图 / 缓存图 / 叠图 / 列图裁段

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from .. import deps
from ..errors import maps_http
from ...core.book import load_book
from ...core.step import KINDS, RunContext
from ...errors import EncodeFailed, ImageMissing
from ...render.overlay import encode_png, overlay

router = APIRouter()



# ── 产物 ─────────────────────────────────────────────────────────────
@router.get("/api/products/{book}/{step}/{key}")
def api_product(book: str, step: str, key: str) -> dict:
    d = deps.product_store().read_raw(book, step, key)
    if d is None:
        raise HTTPException(404, "没有这份产物")
    entry = deps.product_store().manifest(book, step).get(key)
    return {"book": book, "step": step, "key": key,
            "manifest": (entry.__dict__ if entry else None), "products": d}



@router.get("/api/manifest/{book}/{step}")
def api_manifest(book: str, step: str) -> dict:
    m = deps.product_store().manifest(book, step).all()
    return {k: v.__dict__ for k, v in m.items()}



def _png(img: np.ndarray, scale: float | None = None) -> Response:
    """编码在 `render/overlay.encode_png`（与 CLI 共用），这里只包一层 HTTP。

    **不缓存**：叠图画的是产物，重跑一步就变了。原先带 `max-age=60`，
    结果「重跑完点开一看还是旧图」，还以为是算法没生效（2026-09-10 踩过）。
    """
    return Response(encode_png(img, scale), media_type="image/png",
                    headers={"Cache-Control": "no-store"})



@router.get("/api/raw/{book}/{page}.png")
@maps_http
def api_raw(book: str, page: int, scale: float = 0.35) -> Response:
    b = load_book(book)
    p = b.raw_path(page)
    if not p.exists():
        raise ImageMissing("原图缺失")
    img = cv2.imread(str(p))
    return _png(img, scale)



@router.get("/api/cache/{book}/{kind}/{key}.png")
def api_cache(book: str, kind: str, key: str) -> Response:
    import open_guji_cv.steps  # noqa: F401
    if kind not in KINDS or KINDS[kind].storage != "image_cache":
        raise HTTPException(404, "不是缓存图像种类")
    ctx = RunContext(load_book(book), deps.product_store(), deps.image_cache(),
                     log=lambda s: None)
    try:
        path = ctx.materialize(kind, key)
    except Exception as e:   # noqa: BLE001
        raise HTTPException(404, f"拿不到图像: {e}") from e
    return FileResponse(path, media_type="image/png")



# ── 叠图 ─────────────────────────────────────────────────────────────
@router.get("/api/overlay/{book}/{step}/{page}.png")
@maps_http
def api_overlay(book: str, step: str, page: int, scale: float = 0.35) -> Response:
    return _png(overlay(book, step, page, deps.product_store()), scale)



@router.get("/api/cutline/img/{book}/{page}/{col}.png")
@maps_http
def api_cutline_img(book: str, page: int, col: int, y0: int = 0, y1: int = 0) -> Response:
    """列图的一段（上下两格 + 边距），1:1 像素，前端在上面叠可拖的横线。"""
    from ...core.spec import column_key

    path = deps.image_cache().get(book, "column_image", column_key(page, col))
    if path is None:
        raise ImageMissing("没有列图")
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ImageMissing("列图读不出来")
    h = img.shape[0]
    y0 = max(0, min(h - 1, y0)); y1 = max(y0 + 1, min(h, y1 or h))
    ok, buf = cv2.imencode(".png", img[y0:y1])
    if not ok:
        raise EncodeFailed("编码失败")
    return Response(content=buf.tobytes(), media_type="image/png")
