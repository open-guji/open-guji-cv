# -*- coding: utf-8 -*-
"""控制台 · 产物与图像。

数值产物 / 清单 / 原图 / 缓存图 / 叠图 / 列图裁段

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response

from .. import deps
from ..auth import require_reviewer
from ..errors import maps_http
from ...core.book import load_book
from ...core.step import KINDS, RunContext
from ...errors import EncodeFailed, ImageMissing
from ...gates.query import GATES, gate_summary
from ...render.overlay import encode_png, overlay, preclean_overlay, preclean_report
from ...utils.image_io import imread as cv_imread, imwrite as cv_imwrite

router = APIRouter(dependencies=[Depends(require_reviewer)])



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
    img = cv_imread(str(p))
    return _png(img, scale)



@router.get("/api/cache/{book}/{kind}/{key}.png")
def api_cache(book: str, kind: str, key: str, src: str = "raw") -> Response:
    """缓存图像。`src=bin` 时从**整页二值副本**上按同一个 bbox 重裁一张。

    用户 2026-09-16：进字形库的一定是二值的，审阅时也该看二值的。字块缓存
    存的是灰度裁片，所以二值那一路不能读缓存，得拿 `char_index` 里的
    `bbox_page` 去 `binarized/<book>/<page>.png` 上重裁——**同一个坐标、两套图**，
    人可以对照着看。二值副本没生成时**退回灰度**（不报错，页面照常出图）。
    """
    import open_guji_cv.steps  # noqa: F401
    if kind not in KINDS or KINDS[kind].storage != "image_cache":
        raise HTTPException(404, "不是缓存图像种类")
    if src == "bin" and kind == "char_patch":
        got = _char_patch_binarized(book, key)
        if got is not None:
            return got
    try:
        ctx = RunContext(load_book(book), deps.product_store(), deps.image_cache(),
                         log=lambda s: None)
        path = ctx.materialize(kind, key)
    except Exception as e:   # noqa: BLE001
        raise HTTPException(404, f"拿不到图像: {e}") from e
    return FileResponse(path, media_type="image/png")


def _char_patch_binarized(book: str, key: str) -> Response | None:
    """`p0030c01s1` → 从二值页上按该字位的 `bbox_page` 重裁。拿不到就 None（调用方退回灰度）。"""
    import re

    from ...core.step import page_key
    from ...utils.binarized import binarized_or_none

    m = re.fullmatch(r"p(\d+)c(\d+)s(-?\d+)([ab]?)", key)
    if not m:
        return None
    page, col, slot, sub = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
    path = binarized_or_none(book, page)
    if path is None:
        return None
    try:
        ci = deps.product_store().read(book, "cell_shrink", page_key(page), "char_index")
    except Exception:   # noqa: BLE001
        return None
    box = None
    for cc in ci.columns:
        if cc.col != col:
            continue
        for ch in cc.chars:
            if ch.slot == slot and (ch.sub or "") == sub and ch.bbox_page:
                box = ch.bbox_page
                break
        break
    if not box:
        return None
    g = cv_imread(str(path), cv2.IMREAD_GRAYSCALE)
    if g is None:
        return None
    # ⚠️ `bbox_page` 是**右上原点规范空间**（x 向左递增，见 `core/anchor.py` 与
    # `border_geometry` 的坐标约定），而磁盘上的图是左上原点。裁之前必须把 x
    # 镜像回去：`x_img = (W-1) - x_canon`，左右边界同时翻所以要互换。
    # 不翻的后果是**静默裁到另一个字**——实测 p3 c11 s11「鳳」的 bbox_page
    # x=1467，真实位置 x=1243，正好差 (W-1)-1557；y 一点不差，所以看着像
    # 「图没对齐」而不像「坐标系错了」。模板匹配一量就现形（score 0.973）。
    W = g.shape[1]
    bx0, by0, bx1, by1 = (float(v) for v in box)
    x0 = int(round((W - 1) - bx1))
    x1 = int(round((W - 1) - bx0))
    y0, y1 = int(round(by0)), int(round(by1))
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(g.shape[1], x1), min(g.shape[0], y1)
    if x1 <= x0 or y1 <= y0:
        return None
    ok, buf = cv2.imencode(".png", g[y0:y1, x0:x1])
    if not ok:
        return None
    return Response(content=buf.tobytes(), media_type="image/png")



# ── 叠图 ─────────────────────────────────────────────────────────────
@router.get("/api/overlay/{book}/{step}/{page}.png")
@maps_http
def api_overlay(book: str, step: str, page: int, scale: float = 0.35) -> Response:
    return _png(overlay(book, step, page, deps.product_store()), scale)



@router.get("/api/preclean/{book}/{page}")
@maps_http
def api_preclean_report(book: str, page: int) -> dict:
    """Step0 数值报告：每条规则修复前后的带内墨占比，不用再去读 JSON 猜。"""
    return preclean_report(book, page)



@router.get("/api/preclean/{book}/{page}/overlay.png")
@maps_http
def api_preclean_overlay(book: str, page: int, scale: float = 0.35) -> Response:
    """Step0 专用叠图：当初判定的反色带边界画在原图上（红=上沿/蓝=下沿/青=探测行）。"""
    return _png(preclean_overlay(book, page), scale)



@router.get("/api/preclean/{book}/{page}/before.png")
@maps_http
def api_preclean_before(book: str, page: int, scale: float = 0.35) -> Response:
    """原图（修复前），供前端与 precleaned 产物并排/切换对比。"""
    b = load_book(book)
    p = b.raw_path(page)
    if not p.exists():
        raise ImageMissing("原图缺失")
    return _png(cv_imread(str(p)), scale)



@router.get("/api/preclean/{book}/{page}/after.png")
@maps_http
def api_preclean_after(book: str, page: int, scale: float = 0.35) -> Response:
    """修复后的产物图（precleaned/<book>/<page>.png）。没生成就报 404 并提示怎么生成。"""
    from ...utils.preclean import precleaned_path

    p = precleaned_path(book, page)
    if not p.exists():
        raise ImageMissing(f"还没生成，先跑 python -m open_guji_cv.cli_v2 preclean {book}")
    return _png(cv_imread(str(p)), scale)



@router.get("/api/gate/{book}/summary")
@maps_http
def api_gate_summary(book: str, gate: str = "column_gate", pages: str | None = None) -> dict:
    """闸的逐页/逐层汇总——控制台 Step2 面板用，避免前端自己在几十份 gate_manifest 里累加。
    `gate` 见 `gates.query.GATES`；`pages` 同 CLI 的 `--pages`（'90-132' | '3,4,5'），不传就全书。
    """
    if gate not in GATES:
        raise HTTPException(404, f"没有这道闸：{gate}")
    b = load_book(book)
    page_list = b.resolve_pages(pages) if pages else None
    return gate_summary(book, page_list, deps.product_store(), gate=gate)



@router.get("/api/align-ref/{book}/summary")
@maps_http
def api_align_ref_summary(book: str, pages: str | None = None) -> dict:
    """Step5-d 整理本对齐的逐页锚定汇总——控制台面板用，未锚定页带判据明细
    （n_grams/n_votes/vote_frac/dominance），不用再临时写脚本复算。
    `align_ref` 不是闸，不进 `gates.query.GATES`，见 `steps.align_ref.align_ref_summary`。
    """
    from ...steps.align_ref import align_ref_summary

    b = load_book(book)
    page_list = b.resolve_pages(pages) if pages else None
    return align_ref_summary(book, page_list, deps.product_store())



@router.get("/api/ocr-candidates/{book}/summary")
@maps_http
def api_ocr_candidates_summary(book: str, pages: str | None = None) -> dict:
    """Step5-c OCR 候选板块②聚合数字：引擎在线状态 + 候选覆盖率。
    见 `steps.ocr_candidates.ocr_candidates_summary`——07号任务卡判断这一路
    不需要独立查询页，此接口只服务聚合数字，不是单点查询。
    """
    from ...steps.ocr_candidates import ocr_candidates_summary

    b = load_book(book)
    page_list = b.resolve_pages(pages) if pages else None
    return ocr_candidates_summary(book, page_list, deps.product_store())



@router.get("/api/cutline/img/{book}/{page}/{col}.png")
@maps_http
def api_cutline_img(book: str, page: int, col: int, y0: int = 0, y1: int = 0) -> Response:
    """列图的一段（上下两格 + 边距），1:1 像素，前端在上面叠可拖的横线。"""
    from ...core.spec import column_key

    path = deps.image_cache().get(book, "column_image", column_key(page, col))
    if path is None:
        raise ImageMissing("没有列图")
    img = cv_imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ImageMissing("列图读不出来")
    h = img.shape[0]
    y0 = max(0, min(h - 1, y0)); y1 = max(y0 + 1, min(h, y1 or h))
    ok, buf = cv2.imencode(".png", img[y0:y1])
    if not ok:
        raise EncodeFailed("编码失败")
    return Response(content=buf.tobytes(), media_type="image/png")
