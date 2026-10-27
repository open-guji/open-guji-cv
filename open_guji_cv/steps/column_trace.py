"""自由版式 Step2：文字块 → 列（左右是弯缝，`free_columns`）。

没有界行可依：剪切校斜、投影自相关估列距、DP 定列界直线、再在带内走最省墨竖缝。
块里有竖线（界行、表格线）就先按竖线分段。人标了列数（`cols_hint`）就照它分。
算法在 `utils/free_columns.py`。
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from ..core.anchor import bbox_tr_to_tl, x_tl_to_tr, x_tr_to_tl
from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.free_layout import BlockColumnsRec, ColumnRec, FreeColumns, LayoutBlocks
from ..utils.free_blocks import drop_specks, ink_mask
from ..utils.free_columns import block_columns


class ColumnTraceParams(BaseModel):
    bg_win: int = 51
    ink_ratio: float = 0.72
    pitch_min: int = 80            # 列距搜索范围（px，原图尺度）
    pitch_max: int = 300
    seam_band: float = 0.18        # 变缝能偏离直线的幅度（× 列宽）
    sample_step: int = 4           # 缝落盘的采样行距
    min_speck: int = 15            # 面积小于此的墨点先去掉


@register_step
class ColumnTraceStep(Step):
    spec = StepSpec(
        id="column_trace", title="Step2 块内找列（自由版式）", version="1.0", unit="page",
        consumes=("raw_page", "layout_blocks"), produces=("free_columns",), params=ColumnTraceParams,
        code_deps=("open_guji_cv.utils.free_columns", "open_guji_cv.utils.free_blocks"),
        parallel_safe=True,
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: ColumnTraceParams = ctx.params_for(self)  # type: ignore[assignment]
        lb: LayoutBlocks = ctx.product("layout_blocks", page)
        out = FreeColumns(page=page, width=lb.width, height=lb.height)
        todo = [b for b in lb.blocks if b.kind == "text"]
        if lb.page_type == "skip" or not todo:
            return {"free_columns": out}
        W = lb.width
        ink = drop_specks(ink_mask(ctx.raw_page(page), p.bg_win, p.ink_ratio), p.min_speck)
        col_no = 0
        for b in todo:
            x0, y0, x1, y1 = (int(round(v)) for v in bbox_tr_to_tl(b.box, W))
            x0, y0 = max(0, x0), max(0, y0)
            sub = ink[y0:y1, x0:x1]
            if sub.size == 0 or not sub.any():
                continue
            vr = [x_tr_to_tl(x, W) - x0 for x in b.vrules]
            bc = block_columns(sub, b.cols_hint, vr, pitch_range=(p.pitch_min, p.pitch_max),
                               seam_band=p.seam_band)
            out.blocks.append(BlockColumnsRec(block=b.index, n=len(bc.columns), n_source=bc.n_source,
                                              alt_n=bc.alt_n, pitch=bc.pitch, shear=round(bc.shear, 5)))
            rows = np.r_[np.arange(0, y1 - y0, p.sample_step), y1 - y0 - 1]
            for c in bc.columns:                     # 已是右→左
                col_no += 1
                out.columns.append(ColumnRec(
                    col=col_no, block=b.index, y0=float(y0), y1=float(y1), step=p.sample_step,
                    right=[round(x_tl_to_tr(float(c.right[r] + x0), W), 1) for r in rows],
                    left=[round(x_tl_to_tr(float(c.left[r] + x0), W), 1) for r in rows]))
        return {"free_columns": out}
