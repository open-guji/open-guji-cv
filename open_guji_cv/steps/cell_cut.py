"""自由版式 Step3：列 → 字框（`free_cells`）。

列内先分「大字 / 双行小注 / 单行小注」三种区（Viterbi），再在每区按字线切字；
双行小注先走竖缝分右/左两线，读序右线先。不假定每列字数。算法在 books/zengguang_youxue/free_cells.py`。
ruled 块的列（Step2 给了横界栏 `breaks`，1.1 起）先在横界栏处断开，各段分别分区、切字，字框不跨界栏；
ruled 块里界栏（横、竖）的墨先抠掉，不当字。
1.2 起块在分栏线处相接（block_detect 1.5，块边就是线）：每列上下两端 `edge_band` 内的横线墨先抠掉，分栏线不当字。
1.4 起按栏定类型：按字形认出了大字、但大字行不到有墨行一半的栏是混排栏（大字夹双行小注），改用 `segment_mixed` 按字形认大字；
全大字栏照旧逐行分区（窄字不居中也不够宽，按字形认会当成小注）。
同在 1.4（Sheldon 10-28「考虑用识别软件作为辅助」）：有 Step2-b `line_ocr` 的识别行时，非 ruled 块的列改走
`segment_ocr`——识别行定区（大字行、并排的小注行）和每行字数，切点照旧按墨，识别漏掉的段落交给上面的规则。
1.5 起（Sheldon 10-28「拆到每个小块内部同一格式，用一套流程和参数」）：块带人标格式 `fmt` 时按格式选流程——
`plain`（每列一行字，正文或标题）走 `segment_plain`，`mixed` 强制按混排切；不写照旧自动判。
字框带字号 `cid`＝「页-块-行-字」（块号用 `layout_blocks` 的 `label`，行是块内第几列，字是行内读序）。
"""

from __future__ import annotations

import cv2
import numpy as np
from pydantic import BaseModel

from ..core.anchor import bbox_tl_to_tr, bbox_tr_to_tl
from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.free_layout import ColumnRec, FreeCellRec, FreeCells, FreeColumns, FreeOcrLines
from ..books.zengguang_youxue.free_blocks import drop_specks, ink_mask, rule_hlines, rule_vlines
from ..books.zengguang_youxue.free_cells import (big_share, column_span, line_char_heights, note_line_width, seam_rows, segment_column,
                                 segment_mixed, segment_ocr, segment_plain, straighten)
from ..books.zengguang_youxue.free_rectify import rectify_gray


class CellCutParams(BaseModel):
    bg_win: int = 51
    ink_ratio: float = 0.72
    min_speck: int = 15            # 面积小于此的墨点先去掉
    big_ratio: float = 1.45        # 单行区墨宽 > 此 × 页上小字字身 算大字，否则单行小注
    break_pad: int = 6             # 横界栏上下各让这么多（界栏本身的墨不进字框）
    edge_band: int = 25            # 列上下两端这么高内的长横墨（分栏线、框线）不当字
    edge_line: int = 150           # 横墨连续这么长才算线（px）
    mixed_below: float = 0.5       # 1.4 起：按字形认出的大字行占有墨行不到这么多的栏是混排栏（大字夹小注），按字形切
    use_ocr: bool = True           # 1.4 起：有 Step2-b 识别行就用它定区、定字数


def _pieces(col: ColumnRec, h: int, pad: int) -> list[tuple[int, int]]:
    """列（高 h，相对列上端）在横界栏 `breaks` 处断成几段；界栏上下各让 pad。没有界栏就是整列一段。"""
    edges = [0] + [v for y in col.breaks for v in (int(y - col.y0) - pad, int(y - col.y0) + pad)] + [h]
    return [(a, b) for a, b in zip(edges[::2], edges[1::2]) if b - a > 2 * pad]


def _ocr_lines(ctx: RunContext, page: int) -> FreeOcrLines | None:
    """可选上游：没跑 Step2-b（没装识别软件）就 None。"""
    try:
        return ctx.product("free_ocr_lines", page)
    except Exception:
        return None


def _col_lines(ocr: FreeOcrLines, col: ColumnRec, off: np.ndarray, xa: int, y0: int, W: int) -> list[tuple]:
    """这一列的识别行 → 列图坐标（拉直后：逐行减去左缝平移，取行框中线处）。"""
    out = []
    for ln in ocr.lines:
        if ln.col != col.col:
            continue
        x0, ya, x1, yb = bbox_tr_to_tl(ln.box, W)
        ya, yb = int(ya) - y0, int(yb) + 1 - y0
        dx = int(off[min(max((ya + yb) // 2, 0), len(off) - 1)]) + xa
        out.append((int(x0) - dx, ya, int(x1) + 1 - dx, yb, ln.text, ln.score))
    return out


@register_step
class CellCutStep(Step):
    spec = StepSpec(
        id="cell_cut", title="Step3 列内切字（自由版式）", version="1.5", unit="page",
        consumes=("raw_page", "layout_blocks", "free_columns"), produces=("free_cells",), params=CellCutParams,
        optional_consumes=("free_ocr_lines",), optional_consumes_when=(("free_ocr_lines", "use_ocr"),),
        code_deps=("open_guji_cv.books.zengguang_youxue.free_cells", "open_guji_cv.books.zengguang_youxue.free_columns",
                   "open_guji_cv.books.zengguang_youxue.free_blocks", "open_guji_cv.books.zengguang_youxue.free_rectify"),
        parallel_safe=True,
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: CellCutParams = ctx.params_for(self)  # type: ignore[assignment]
        fc: FreeColumns = ctx.product("free_columns", page)
        out = FreeCells(page=page, width=fc.width, height=fc.height)
        if not fc.columns:
            return {"free_cells": out}
        W = fc.width
        lb = ctx.product("layout_blocks", page)
        gray = rectify_gray(ctx.raw_page(page), lb.warp)
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
            left, right = seam_rows(col, W)
            xa, xb = column_span(col, W)
            src = (ink_t if col.block in ruled else ink)[y0:y1, xa:xb].copy()
            e = min(p.edge_band, (y1 - y0) // 4)
            for a, b in ((0, e), (y1 - y0 - e, y1 - y0)):
                src[a:b] &= ~hrules[y0 + a:y0 + b, xa:xb]
            cimg, off = straighten(src, left - xa, right - xa)
            cols.append((col, cimg, off, xa, y0, _pieces(col, y1 - y0, p.break_pad), left, right))
        # 两遍：先量页上双行小注的字线墨宽（小字字身），再拿它分大字与单行小注
        widths = [w for _, cimg, _, _, _, pieces, *_ in cols for a, b in pieces for w in note_line_width(cimg[a:b])]
        small_em = float(np.median(widths)) if len(widths) >= 6 else None
        # 按栏定类型：全大字栏照逐行分区切；混排栏（大字夹小注）按字形认大字（1.4，Sheldon 10-28）
        share: dict[int, list[int]] = {}
        for col, cimg, _, _, _, pieces, *_ in cols:
            acc = share.setdefault(col.block, [0, 0])
            for a, b in pieces:
                big, tot = big_share(cimg[a:b])
                acc[0] += big
                acc[1] += tot
        ocr = _ocr_lines(ctx, page) if p.use_ocr else None
        fmt = {b.index: b.fmt for b in lb.blocks}
        label = {b.index: b.label or str(b.index) for b in lb.blocks}
        line_no: dict[int, int] = {}
        mixed = {blk for blk, (big, tot) in share.items() if blk not in ruled and 0 < big < p.mixed_below * tot}
        # 每列一行字的块：块里各列可信识别行的字高中位数，给没读出字的列当字高先验
        em_plain: dict[int, list[float]] = {}
        if ocr is not None:
            for col, *_ in cols:
                if fmt.get(col.block) == "plain":
                    em_plain.setdefault(col.block, []).extend(
                        line_char_heights(_col_lines(ocr, col, np.zeros(1, int), 0, int(col.y0), W)))
        for col, cimg, off, xa, y0, pieces, left, right in cols:
            order = zone = 0
            line_no[col.block] = line = line_no.get(col.block, 0) + 1
            for k, (a, b) in enumerate(pieces):
                lines = _col_lines(ocr, col, off, xa, y0 + a, W) if ocr is not None and col.block not in ruled else []
                if fmt.get(col.block) == "plain":
                    hs = em_plain.get(col.block)
                    found = segment_plain(cimg[a:b], lines, col_w=float(np.median(right - left)),
                                          em_hint=float(np.median(hs)) if hs else None)
                elif lines:
                    found = segment_ocr(cimg[a:b], lines)
                elif col.block in mixed or fmt.get(col.block) == "mixed":
                    found = segment_mixed(cimg[a:b])
                else:
                    found = segment_column(cimg[a:b], small_em=small_em, big_ratio=p.big_ratio)
                for c in found:
                    order += 1
                    ym = a + (c.y0 + c.y1) // 2
                    dx = int(off[min(ym, len(off) - 1)]) + xa
                    box_tl = (float(c.x0 + dx), float(c.y0 + a + y0), float(c.x1 - 1 + dx), float(c.y1 - 1 + a + y0))
                    out.cells.append(FreeCellRec(col=col.col, order=order, kind=c.kind, zone=zone + c.zone + 1,
                                                 rule_seg=k + 1 if col.breaks else 0,
                                                 block=label.get(col.block, str(col.block)), line=line,
                                                 cid=f"{page}-{label.get(col.block, col.block)}-{line}-{order}",
                                                 box=bbox_tl_to_tr(box_tl, W), ink=c.ink))
                zone += max((c.zone + 1 for c in found), default=0)
        out.n_cells = len(out.cells)
        return {"free_cells": out}
