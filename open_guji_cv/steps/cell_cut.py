"""自由版式 Step3：列 → 字框（`free_cells`）。

列内先分「大字 / 双行小注 / 单行小注」三种区（Viterbi），再在每区按字线切字；
双行小注先走竖缝分右/左两线，读序右线先。不假定每列字数。算法在 `utils/free_cells.py`。
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from ..core.anchor import bbox_tl_to_tr, x_tr_to_tl
from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.free_layout import ColumnRec, FreeCellRec, FreeCells, FreeColumns
from ..utils.free_blocks import drop_specks, ink_mask
from ..utils.free_cells import note_line_width, segment_column, straighten


class CellCutParams(BaseModel):
    bg_win: int = 51
    ink_ratio: float = 0.72
    min_speck: int = 15            # 面积小于此的墨点先去掉
    big_ratio: float = 1.45        # 单行区墨宽 > 此 × 页上小字字身 算大字，否则单行小注


def _seam_rows(col: ColumnRec, W: int) -> tuple[np.ndarray, np.ndarray]:
    """采样的缝 → 逐行左右缝 x（左上原点，相对列所在块的 y0）。"""
    h = int(col.y1 - col.y0)
    ys = np.r_[np.arange(0, h, col.step), h - 1][:len(col.right)]
    rows = np.arange(h)
    right = np.interp(rows, ys, [x_tr_to_tl(x, W) for x in col.right])
    left = np.interp(rows, ys, [x_tr_to_tl(x, W) for x in col.left])
    return np.round(left).astype(int), np.round(right).astype(int)


@register_step
class CellCutStep(Step):
    spec = StepSpec(
        id="cell_cut", title="Step3 列内切字（自由版式）", version="1.0", unit="page",
        consumes=("raw_page", "free_columns"), produces=("free_cells",), params=CellCutParams,
        code_deps=("open_guji_cv.utils.free_cells", "open_guji_cv.utils.free_columns",
                   "open_guji_cv.utils.free_blocks"),
        parallel_safe=True,
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: CellCutParams = ctx.params_for(self)  # type: ignore[assignment]
        fc: FreeColumns = ctx.product("free_columns", page)
        out = FreeCells(page=page, width=fc.width, height=fc.height)
        if not fc.columns:
            return {"free_cells": out}
        W = fc.width
        ink = drop_specks(ink_mask(ctx.raw_page(page), p.bg_win, p.ink_ratio), p.min_speck)
        cols = []
        for col in fc.columns:
            y0, y1 = int(col.y0), int(col.y1)
            left, right = _seam_rows(col, W)
            xa = max(0, int(left.min()) - 4)
            xb = min(W, int(right.max()) + 5)
            cimg, off = straighten(ink[y0:y1, xa:xb], left - xa, right - xa)
            cols.append((col, cimg, off, xa, y0))
        # 两遍：先量页上双行小注的字线墨宽（小字字身），再拿它分大字与单行小注
        widths = [w for _, cimg, *_ in cols for w in note_line_width(cimg)]
        small_em = float(np.median(widths)) if len(widths) >= 6 else None
        for col, cimg, off, xa, y0 in cols:
            for i, c in enumerate(segment_column(cimg, small_em=small_em, big_ratio=p.big_ratio)):
                ym = (c.y0 + c.y1) // 2
                dx = int(off[min(ym, len(off) - 1)]) + xa
                box_tl = (float(c.x0 + dx), float(c.y0 + y0), float(c.x1 - 1 + dx), float(c.y1 - 1 + y0))
                out.cells.append(FreeCellRec(col=col.col, order=i + 1, kind=c.kind, zone=c.zone + 1,
                                             box=bbox_tl_to_tr(box_tl, W), ink=c.ink))
        out.n_cells = len(out.cells)
        return {"free_cells": out}
