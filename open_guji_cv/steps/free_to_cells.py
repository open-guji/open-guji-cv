"""2d′ 自由版式转标准字格（`free_to_cells`，2026-11-28 默认链第二期，设计 https://claude.ai/artifact/99ihHT9o84MSKtB59YDWMp 第三、五节）。

自由版式（`layout: free`）的切字结果是另立的种类：`free_columns`（每列左右弯缝）＋`free_cells`（页面坐标字框）。
2e `cell_shrink` 起的骨架缺省各步要的是标准的 `cells`＋`column_windows`＋`column_image`。本步只做换算，不重新切：

- **列图**：弯缝之间的像素逐行平移到左对齐（与 `cell_cut` 同一套 `straighten`，`impl/free/free_map.column_rows`），
  从拉正后的页（`layout_blocks.warp`）上取灰度；缝外、ruled 块的界栏、列两端 `edge_band` 内的长横墨（分栏线、框线）抹白，
  与 `cell_cut` 切字时看到的墨一致。
- **字格**：`free_cells` 的页面框换回列图坐标（逐位可逆：`cell_cut` 用格中线那行的平移量放回页面，这里用同一行减回来）。
  大字、单行小注各占一个格位；双行小注一个区里右行第 i 字与左行第 i 字配成同一格位（a／b 两半，各自的 y 进
  `jiazhu_y`，`cell_shrink` 按半格裁）；一行比另一行多出的字单独占格位。`order` 是 `free_cells` 的读序（小注右行先、左行后）。
- **列窗**：`ColumnWindowRec.free_map` 记下逐行平移与页的拉正参数，`ColumnMapper.of` 据此把列图坐标反算回原图，
  `quad_page`、`cell_shrink` 的 `bbox_page` 都落在原图上（右上原点）。

不做的事：不改切分（切错了改 `cell_cut`）；不出 `column_raw`（`cell_shrink` 只在 `inner_frame_only` 时要它，free 套书关着）；
不出 `cut_candidates`、折线 `seam_*`。坐标：`cells`、`column_image` 在列图坐标（左上原点），`quad_page` 右上原点。
"""

from __future__ import annotations

import cv2
import numpy as np
from pydantic import BaseModel

from ..core.anchor import bbox_tr_to_tl
from ..core.spec import StepSpec, column_key, parse_key
from ..core.step import RunContext, Step, register_step
from ..impl.free.free_blocks import ink_mask, rule_hlines, rule_vlines
from ..impl.free.free_map import column_rows, rows_runs, straighten_gray
from ..impl.free.free_rectify import rectify_gray
from ..products.kinds.borders import VLineRec
from ..products.kinds.cells import CellRec, ColumnCells, PageCells
from ..products.kinds.columns import BorderTrim, ColumnWindowRec, PageWindows
from ..products.kinds.free_layout import ColumnRec, FreeCellRec, FreeCells, FreeColumns
from ._warpmap import ColumnMapper

SUB = {"jiazhu_a": "a", "jiazhu_b": "b"}


class FreeToCellsParams(BaseModel):
    # 列图清理，缺省与 `cell_cut` 的同名参数相同（两边切字看到的墨要一致；某书改了 cell_cut 的，这里跟着写）
    bg_win: int = 51
    ink_ratio: float = 0.72
    break_pad: int = 6             # ruled 块界栏（横、竖）的墨往外胖这么多再抹白
    edge_band: int = 25            # 列上下两端这么高内的长横墨（分栏线、框线）抹白
    edge_line: int = 150           # 横墨连续这么长才算线（px）
    pad: int = 2                   # 列图在左右缝外各留几 px（= `free_cells.straighten` 的 pad）


def _clean_mask(gray: np.ndarray, fc: FreeColumns, p: FreeToCellsParams) -> np.ndarray:
    """要抹白的像素（整页 bool）：ruled 块的界栏、长横墨。列端 `edge_band` 的限制在逐列裁时再加。"""
    ink = ink_mask(gray, p.bg_win, p.ink_ratio)
    hrules = cv2.dilate(cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_OPEN, np.ones((1, p.edge_line), np.uint8)),
                        np.ones((5, 1), np.uint8)) > 0
    rules = np.zeros_like(hrules)
    if any(b.n_source == "ruled" for b in fc.blocks):
        k = 2 * p.break_pad + 1
        rules = (cv2.dilate(rule_hlines(gray, p.bg_win), np.ones((k, 1), np.uint8))
                 | cv2.dilate(rule_vlines(gray, p.bg_win), np.ones((1, k), np.uint8))) > 0
    return hrules, rules


def _column_image(gray, col: ColumnRec, W: int, ruled: set, hrules, rules, p: FreeToCellsParams):
    """一列 → (列图, xa, L, wc)。"""
    y0, y1 = int(col.y0), int(col.y1)
    xa, _xb, L, R, wc = column_rows(col, W, p.pad)
    drop = np.zeros(gray.shape[:2], bool)
    e = min(p.edge_band, (y1 - y0) // 4)
    for a, b in ((y0, y0 + e), (y1 - e, y1)):
        drop[a:b] |= hrules[a:b]
    if col.block in ruled:
        drop[y0:y1] |= rules[y0:y1]
    img = straighten_gray(gray, y0, y1, xa, L, R, wc, keep=~drop)
    return img, xa, L, wc


def _to_col(c: FreeCellRec, W: int, xa: int, L: np.ndarray, y0: int) -> tuple[float, float, float, float]:
    """页面框（右上原点、两端含）→ 列图框 [x0, x1)、[y0, y1)。cell_cut 放回页面时用的是格中线那行的平移量。"""
    x0, ya, x1, yb = bbox_tr_to_tl(c.box, W)
    cy0, cy1 = int(round(ya)) - y0, int(round(yb)) + 1 - y0
    ym = min(max((cy0 + cy1) // 2, 0), len(L) - 1)
    dx = int(L[ym]) + xa
    return float(int(round(x0)) - dx), float(cy0), float(int(round(x1)) + 1 - dx), float(cy1)


def column_cells(col: int, cells: list[FreeCellRec], boxes: dict[int, tuple], mapper: ColumnMapper | None,
                 wc: int, label: str = "") -> ColumnCells:
    """一列的 free 字格（已按读序）→ `ColumnCells`。`boxes`：id(cell) → 列图框。"""
    groups: list[list[FreeCellRec]] = []          # 每组一个格位
    by_zone: dict[int, list[FreeCellRec]] = {}
    for c in cells:
        by_zone.setdefault(c.zone, []).append(c)
    for z in sorted(by_zone, key=lambda z: min(boxes[id(c)][1] for c in by_zone[z])):
        zc = by_zone[z]
        if any(c.kind in SUB for c in zc):
            a = sorted((c for c in zc if c.kind == "jiazhu_a"), key=lambda c: boxes[id(c)][1])
            b = sorted((c for c in zc if c.kind == "jiazhu_b"), key=lambda c: boxes[id(c)][1])
            rest = [c for c in zc if c.kind not in SUB]
            for i in range(max(len(a), len(b))):
                groups.append([x for x in (a[i] if i < len(a) else None, b[i] if i < len(b) else None) if x])
            groups.extend([c] for c in rest)
        else:
            groups.extend([c] for c in zc)
    groups.sort(key=lambda g: min(boxes[id(c)][1] for c in g))
    flags = ["free"] + ([f"block:{label}"] if label else [])
    if not groups:
        # 空列不给 content_x：cell_shrink 整页量格高、框线位只看有 content_x 的列（period 为空会把中位数算坏）
        return ColumnCells(col=col, ok=True, n_body_slots=0, flags=flags + ["empty"])
    spans = [(min(boxes[id(c)][1] for c in g), max(boxes[id(c)][3] for c in g)) for g in groups]
    bounds = [spans[0][0]] + [(spans[k][1] + spans[k + 1][0]) / 2 for k in range(len(spans) - 1)] + [spans[-1][1]]
    out: list[CellRec] = []
    for pos, g in enumerate(groups, start=1):
        gap = None
        if len(g) == 2:          # 右行 a 在列图右边：缝在 a 左沿与 b 右沿之间
            ba, bb = boxes[id(g[0])], boxes[id(g[1])]
            gap = (ba[0] + bb[2]) / 2
        elif g[0].kind in SUB:
            gap = wc / 2
        for c in g:
            x0, y0, x1, y1 = boxes[id(c)]
            out.append(CellRec(
                slot=pos, pos=pos, y0=y0, y1=y1, x0=x0, x1=x1, kind=c.kind, sub=SUB.get(c.kind),
                order=c.order - 1, gap_center=None if gap is None else float(gap),
                ink_ratio=round(c.ink / max(1.0, (x1 - x0) * (y1 - y0)), 4),
                quad_page=(None if mapper is None else
                           [(round(x, 2), round(y, 2)) for x, y in mapper.quad_tr(x0, y0, x1, y1)])))
    big = [c.y1 - c.y0 for c in out if c.kind == "char"]
    period = float(np.median(big)) if big else float(np.median(np.diff(bounds)))
    return ColumnCells(col=col, ok=True, n_body_slots=len(groups), period=period, ref_w=float(wc),
                       content_x=(0.0, float(wc)), boundaries=[float(v) for v in bounds],
                       cells=sorted(out, key=lambda c: (c.pos, c.sub or "")), flags=flags)


@register_step
class FreeToCellsStep(Step):
    spec = StepSpec(
        id="free_to_cells", title="2d′ 自由版式转标准字格", version="1.0", unit="column",
        consumes=("raw_page", "layout_blocks", "free_columns", "free_cells"),
        produces=("cells", "column_windows", "column_image"), params=FreeToCellsParams,
        code_deps=("open_guji_cv.impl.free.free_map", "open_guji_cv.impl.free.free_cells",
                   "open_guji_cv.impl.free.free_blocks", "open_guji_cv.impl.free.free_rectify",
                   "open_guji_cv.steps._warpmap"),
        parallel_safe=True,
    )

    def _page(self, ctx: RunContext, page: int):
        p: FreeToCellsParams = ctx.params_for(self)  # type: ignore[assignment]
        fc: FreeColumns = ctx.product("free_columns", page)
        lb = ctx.product("layout_blocks", page)
        gray = rectify_gray(ctx.raw_page(page), lb.warp)
        if gray.ndim == 3:
            gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
        hrules, rules = _clean_mask(gray, fc, p) if fc.columns else (None, None)
        ruled = {b.block for b in fc.blocks if b.n_source == "ruled"}
        return p, fc, lb, gray, hrules, rules, ruled

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p, fc, lb, gray, hrules, rules, ruled = self._page(ctx, page)
        W, H = fc.width, fc.height
        fcells: FreeCells = ctx.product("free_cells", page)
        label = {b.index: b.label or str(b.index) for b in lb.blocks}
        recs: list[ColumnWindowRec] = []
        cols: list[ColumnCells] = []
        for col in fc.columns:
            img, xa, L, wc = _column_image(gray, col, W, ruled, hrules, rules, p)
            ctx.cache.put(ctx.book.id, "column_image", column_key(page, col.col), img)
            y0, y1 = int(col.y0), int(col.y1)
            fm = {"xa": int(xa), "y0": y0, "h": y1 - y0, "w": int(wc), "rows": rows_runs(L), "warp": lb.warp}
            xl, xr = W - 1 - (xa + float(L.min())), W - 1 - (xa + float(L.max()) + wc - 1)   # 右上原点：左线 x 大
            rec = ColumnWindowRec(
                col=col.col, left_line=VLineRec(x_at_top=xl, slope=0.0),
                right_line=VLineRec(x_at_top=xr, slope=0.0),
                top_y=float(y0), bottom_y=float(y1), border_top_y=float(y0), border_bottom_y=float(y1),
                border_top_in_column=0.0, border_bottom_in_column=float(y1 - y0),
                warped_size=(int(wc), int(y1 - y0)), band=(0, int(wc)),
                trim_top=BorderTrim(px=0, case="none"), trim_bottom=BorderTrim(px=0, case="none"),
                side_floor=0.0, free_map=fm)
            recs.append(rec)
            mine = sorted((c for c in fcells.cells if c.col == col.col), key=lambda c: c.order)
            boxes = {id(c): _to_col(c, W, xa, L, y0) for c in mine}
            cols.append(column_cells(col.col, mine, boxes, ColumnMapper.of(W, rec), wc,
                                     label.get(col.block, str(col.block))))
        periods = [c.period for c in cols if c.period]
        return {"column_windows": PageWindows(page=page, page_size=(int(W), int(H)), vline_segments=1,
                                              denoised=False, columns=recs),
                "cells": PageCells(page=page, period=float(np.median(periods)) if periods else None,
                                   ref_w=float(np.median([r.warped_size[0] for r in recs])) if recs else None,
                                   columns=cols)}

    def render(self, ctx: RunContext, kind_id: str, key: str) -> np.ndarray:
        page, col, _ = parse_key(key)
        if col is None:
            raise ValueError(f"{kind_id} 的键必须带列号: {key}")
        p, fc, lb, gray, hrules, rules, ruled = self._page(ctx, page)
        rec = next((c for c in fc.columns if c.col == col), None)
        if rec is None:
            raise KeyError(f"第 {page} 页没有第 {col} 列")
        return _column_image(gray, rec, fc.width, ruled, hrules, rules, p)[0]
