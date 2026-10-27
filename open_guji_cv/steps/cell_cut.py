"""自由版式 Step3：列 → 字框（`free_cells`）。

列内先分「大字 / 双行小注 / 单行小注」三种区（Viterbi），再在每区按字线切字；
双行小注先走竖缝分右/左两线，读序右线先。不假定每列字数。算法在 `utils/free_cells.py`。
ruled 块的列（Step2 给了横界栏 `breaks`，1.1 起）先在横界栏处断开，各段分别分区、切字，字框不跨界栏；
ruled 块里界栏（横、竖）的墨先抠掉，不当字。
1.2 起块在分栏线处相接（block_detect 1.5，块边就是线）：每列上下两端 `edge_band` 内的横线墨先抠掉，分栏线不当字。
"""

from __future__ import annotations

import cv2
import numpy as np
from pydantic import BaseModel

from ..core.anchor import bbox_tl_to_tr, x_tr_to_tl
from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.free_layout import ColumnRec, FreeCellRec, FreeCells, FreeColumns
from ..utils.free_blocks import drop_specks, ink_mask, rule_hlines, rule_vlines
from ..utils.free_cells import note_line_width, segment_column, straighten


class CellCutParams(BaseModel):
    bg_win: int = 51
    ink_ratio: float = 0.72
    min_speck: int = 15            # 面积小于此的墨点先去掉
    big_ratio: float = 1.45        # 单行区墨宽 > 此 × 页上小字字身 算大字，否则单行小注
    break_pad: int = 6             # 横界栏上下各让这么多（界栏本身的墨不进字框）
    edge_band: int = 25            # 列上下两端这么高内的长横墨（分栏线、框线）不当字
    edge_line: int = 150           # 横墨连续这么长才算线（px）


def _seam_rows(col: ColumnRec, W: int) -> tuple[np.ndarray, np.ndarray]:
    """采样的缝 → 逐行左右缝 x（左上原点，相对列所在块的 y0）。"""
    h = int(col.y1 - col.y0)
    ys = np.r_[np.arange(0, h, col.step), h - 1][:len(col.right)]
    rows = np.arange(h)
    right = np.interp(rows, ys, [x_tr_to_tl(x, W) for x in col.right])
    left = np.interp(rows, ys, [x_tr_to_tl(x, W) for x in col.left])
    return np.round(left).astype(int), np.round(right).astype(int)


def _pieces(col: ColumnRec, h: int, pad: int) -> list[tuple[int, int]]:
    """列（高 h，相对列上端）在横界栏 `breaks` 处断成几段；界栏上下各让 pad。没有界栏就是整列一段。"""
    edges = [0] + [v for y in col.breaks for v in (int(y - col.y0) - pad, int(y - col.y0) + pad)] + [h]
    return [(a, b) for a, b in zip(edges[::2], edges[1::2]) if b - a > 2 * pad]


@register_step
class CellCutStep(Step):
    spec = StepSpec(
        id="cell_cut", title="Step3 列内切字（自由版式）", version="1.2", unit="page",
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
        gray = ctx.raw_page(page)
        ink = drop_specks(ink_mask(gray, p.bg_win, p.ink_ratio), p.min_speck)
        ruled = {b.block for b in fc.blocks if b.n_source == "ruled"}
        if ruled:    # 有界栏的块：界栏的墨（含伸进空处、没够上断开线的半截）不算字
            k = 2 * p.break_pad + 1
            rules = (cv2.dilate(rule_hlines(gray, p.bg_win), np.ones((k, 1), np.uint8))
                     | cv2.dilate(rule_vlines(gray, p.bg_win), np.ones((1, k), np.uint8))) > 0
            ink_t = drop_specks(ink & ~rules, p.min_speck)
        # 长横墨（分栏线、框线；字的横画没这么长），边上再胖 2px
        hrules = cv2.dilate(cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_OPEN, np.ones((1, p.edge_line), np.uint8)),
                            np.ones((5, 1), np.uint8)) > 0
        cols = []
        for col in fc.columns:
            y0, y1 = int(col.y0), int(col.y1)
            left, right = _seam_rows(col, W)
            xa = max(0, int(left.min()) - 4)
            xb = min(W, int(right.max()) + 5)
            src = (ink_t if col.block in ruled else ink)[y0:y1, xa:xb].copy()
            e = min(p.edge_band, (y1 - y0) // 4)
            for a, b in ((0, e), (y1 - y0 - e, y1 - y0)):
                src[a:b] &= ~hrules[y0 + a:y0 + b, xa:xb]
            cimg, off = straighten(src, left - xa, right - xa)
            cols.append((col, cimg, off, xa, y0, _pieces(col, y1 - y0, p.break_pad)))
        # 两遍：先量页上双行小注的字线墨宽（小字字身），再拿它分大字与单行小注
        widths = [w for _, cimg, _, _, _, pieces in cols for a, b in pieces for w in note_line_width(cimg[a:b])]
        small_em = float(np.median(widths)) if len(widths) >= 6 else None
        for col, cimg, off, xa, y0, pieces in cols:
            order = zone = 0
            for k, (a, b) in enumerate(pieces):
                found = segment_column(cimg[a:b], small_em=small_em, big_ratio=p.big_ratio)
                for c in found:
                    order += 1
                    ym = a + (c.y0 + c.y1) // 2
                    dx = int(off[min(ym, len(off) - 1)]) + xa
                    box_tl = (float(c.x0 + dx), float(c.y0 + a + y0), float(c.x1 - 1 + dx), float(c.y1 - 1 + a + y0))
                    out.cells.append(FreeCellRec(col=col.col, order=order, kind=c.kind, zone=zone + c.zone + 1,
                                                 rule_seg=k + 1 if col.breaks else 0,
                                                 box=bbox_tl_to_tr(box_tl, W), ink=c.ink))
                zone += max((c.zone + 1 for c in found), default=0)
        out.n_cells = len(out.cells)
        return {"free_cells": out}
