# -*- coding: utf-8 -*-
"""Step1/Step2 边框类裁决的卡片装配——从 artifact 迁进控制台。

用户 2026-09-11 定：「以后完全不走 artifact，都走控制台」。这四类裁决原先由
`scripts/build_border_gold_reviews.py`（cols / head / outer）与
`scripts/build_column_border_review.py`（colborder）生成一次性 Artifact 网页，
标注后靠脚本导出金标。搬进控制台后不再现算/现抽样——**直接读已经跑出来的
`borders` / `column_windows` 产物**，卡片就是"这一页/这一列现在的探测结果"，
跟控制台其余叠图口径一致（数值长期、图像即算）。

裁决落地不变：写 `/api/events`（kind=`verdict` 给 cols/head/outer，
`border_class` 给 colborder），路由表已有映射（`feedback/routes.py`），
不新增消费者。

卡片 id 规则（喂给 `feedback/harvest.parse_card_id`）：
    cols:{book}:{page}            outer:{book}:{page}:{top|bottom}
    head:{book}:{page}            colborder:{book}:{page}:{col}:{top|bot}
"""

from __future__ import annotations

import cv2
import numpy as np

from ..core.book import load_book
from ..core.spec import page_key
from ..core.step import RunContext
from ..errors import ImageMissing, ProductMissing
from ..products.store import ProductStore
from ..utils.column_projection import (
    column_row_profile,
    column_text_band,
    denoise_column,
    page_column_windows,
    strip_column_rules,
)

HEAD_UP, HEAD_DN = 250, 45
STRIP_W, STRIP_PAD = 480, 42
CROP_ROWS = 220


def _borders(store: ProductStore, book: str, page: int):
    d = store.read(book, "border_detect", page_key(page), "borders")
    return d.to_result() if d else None


def _read_gray(book: str, page: int):
    b = load_book(book)
    p = b.raw_path(page)
    if not p.exists():
        raise ImageMissing(f"原图缺失: {p}")
    img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ImageMissing(f"原图读不出来: {p}")
    return img


def _need_borders(store: ProductStore, book: str, page: int):
    res = _borders(store, book, page)
    if res is None:
        raise ProductMissing(f"没有 border_detect 产物: {book}/{page}")
    return res


def cols_cards(store: ProductStore, book: str, pages: list[int], page_w: int = 560) -> list[dict]:
    """列探测卡：整页缩图 + 界行叠加（复用 `render/overlay.py` 的画法与颜色）。"""
    out = []
    for pg in pages:
        res = _borders(store, book, pg)
        if res is None:
            continue
        out.append(dict(id=f"cols:{book}:{pg}", kind="cols", book=book, page=pg,
                        n_cols=len(res.verticals),
                        img=f"/api/border-review/img/{book}/{pg}.jpg?kind=cols&w={page_w}"))
    return out


def head_cards(store: ProductStore, book: str, pages: list[int]) -> list[dict]:
    """抬头有无卡：上版框横带原图，不叠任何探测结果（要量召回率）。"""
    out = []
    for pg in pages:
        res = _borders(store, book, pg)
        if res is None:
            continue
        out.append(dict(id=f"head:{book}:{pg}", kind="head", book=book, page=pg,
                        img=f"/api/border-review/img/{book}/{pg}.jpg?kind=head"))
    return out


def outer_cards(store: ProductStore, book: str, pages: list[int]) -> list[dict]:
    """外框外延卡：上/下各一张，叠已存的外延偏移线。没探到外框的页不出卡。"""
    out = []
    for pg in pages:
        res = _borders(store, book, pg)
        if res is None:
            continue
        for side, off in (("top", res.top_outer_offset), ("bottom", res.bottom_outer_offset)):
            if off is None:
                continue
            out.append(dict(id=f"outer:{book}:{pg}:{side}", kind="outer", book=book, page=pg,
                            side=side, offset=round(float(off), 2),
                            img=f"/api/border-review/img/{book}/{pg}.jpg?kind=outer&side={side}"))
    return out


def colborder_cards(store: ProductStore, book: str, pages: list[int]) -> list[dict]:
    """单列矫正·上下版框核校卡：一列出两张（上端/下端），只记类别不记坐标。"""
    out = []
    for pg in pages:
        res = _borders(store, book, pg)
        if res is None:
            continue
        for win in page_column_windows(res):
            for end in ("top", "bot"):
                out.append(dict(
                    id=f"colborder:{book}:{pg}:{win.col}:{end}", kind="colborder",
                    book=book, page=pg, col=win.col, end=end, raised=win.raised,
                    img=(f"/api/border-review/img/{book}/{pg}.jpg"
                        f"?kind=colborder&col={win.col}&side={end}")))
    return out


# ── 图像装配（供 console/routers/border_review.py 的图像端点调用）──────

def render_cols_img(store: ProductStore, book: str, page: int, page_w: int = 560) -> np.ndarray:
    from ..render.overlay import draw_vline

    gray = _read_gray(book, page)
    res = _need_borders(store, book, page)
    h, w = gray.shape
    sc = page_w / w
    thumb = cv2.cvtColor(cv2.resize(gray, (page_w, int(h * sc)), interpolation=cv2.INTER_AREA),
                         cv2.COLOR_GRAY2BGR)
    H2, W2 = thumb.shape[:2]
    for v in res.verticals:
        rec = dict(x_at_top=v.x_at_top * sc, slope=v.slope,
                  k2=None if v.k2 is None else v.k2, k3=v.k3,
                  y1=None if v.y1 is None else v.y1 * sc, y2=None if v.y2 is None else v.y2 * sc)
        draw_vline(thumb, rec, W2, H2, (0, 40, 235), thick=1)
    return thumb


def render_head_img(store: ProductStore, book: str, page: int, head_w: int = 900) -> np.ndarray:
    gray = _read_gray(book, page)
    res = _need_borders(store, book, page)
    h, w = gray.shape
    ytop = int(res.top.y_at((w - 1) - w // 2))
    lo, hi = max(0, ytop - HEAD_UP), min(h, ytop + HEAD_DN)
    vx = sorted((w - 1) - v.x_at(h / 2.0) for v in res.verticals)
    x0, x1 = int(vx[0]) - 30, int(vx[-1]) + 30
    band = gray[lo:hi, max(0, x0):min(w, x1)]
    return cv2.resize(band, (head_w, int(band.shape[0] * head_w / max(1, band.shape[1]))),
                      interpolation=cv2.INTER_AREA)


def render_outer_img(store: ProductStore, book: str, page: int, side: str,
                     strip_w: int = STRIP_W, zoom: int = 2) -> np.ndarray:
    gray = _read_gray(book, page)
    res = _need_borders(store, book, page)
    h, w = gray.shape
    L = res.top if side == "top" else res.bottom
    sign = -1.0 if side == "top" else 1.0
    off = res.top_outer_offset if side == "top" else res.bottom_outer_offset
    vx = sorted((w - 1) - v.x_at(h / 2.0) for v in res.verticals)
    cx = (int(vx[0]) + int(vx[-1])) // 2 - strip_w // 2
    cx = max(0, min(w - strip_w, cx))
    ymid = L.y_at((w - 1) - (cx + strip_w // 2))
    e = float(off) * sign if off is not None else 0.0
    top_y = max(0, int(ymid + min(0, e) - STRIP_PAD))
    bot_y = min(h, int(ymid + max(0, e) + STRIP_PAD))
    strip = cv2.cvtColor(gray[top_y:bot_y, cx:cx + strip_w], cv2.COLOR_GRAY2BGR)
    if off is not None:
        for i in range(strip_w):
            if (i // 11) % 2:
                continue
            y = int(round(L.y_at((w - 1) - (cx + i)) + e)) - top_y
            if 0 <= y < strip.shape[0]:
                strip[y, i] = (0, 40, 235)
    return cv2.resize(strip, (strip_w * zoom, strip.shape[0] * zoom), interpolation=cv2.INTER_NEAREST)


def render_colborder_img(ctx: RunContext, book: str, page: int, col: int, end: str
                         ) -> tuple[np.ndarray, list[float]]:
    """返回 (裁剪灰度图, 沿水平方向投影 0~1 列表)。顺序固化：定带 → 抹侧 → 只在带内算投影。"""
    from ..core.spec import column_key

    try:
        path = ctx.materialize("column_image", column_key(page, col))
    except Exception as e:   # noqa: BLE001
        raise ImageMissing(f"列图算不出来: {e}") from e
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ImageMissing("列图读不出来")
    denoised = denoise_column(img)
    band = column_text_band(denoised)
    no_rules = strip_column_rules(denoised)
    core = no_rules[:, band[0]:band[1]]
    prof = column_row_profile(no_rules, band)
    h = core.shape[0]
    if end == "top":
        crop, pslice = core[:CROP_ROWS], prof[:CROP_ROWS]
    else:
        crop, pslice = core[h - CROP_ROWS:][::-1], prof[h - CROP_ROWS:][::-1]
    return crop, [float(v) for v in pslice]
