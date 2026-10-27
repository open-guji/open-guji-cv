"""自由版式 Step2：文字块 → 列（左右是弯缝，`free_columns`）。

有列距先验（人标 `pitch`，或参数 `pitch_prior`）或人标列数时走等宽网格（`grid_columns`）：
浅界行当好切线、列宽贴近列距、网格两端浮动但要盖住正文的墨（版心不算）。
都没有时退回自估：剪切校斜、投影自相关估列距、DP 定列界直线、带内走最省墨竖缝；
块里有竖线（界行、表格线）就先按竖线分段。
算法在 `utils/free_columns.py`。
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from ..core.anchor import bbox_tr_to_tl, x_tl_to_tr, x_tr_to_tl
from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.free_layout import BlockColumnsRec, ColumnRec, FreeColumns, LayoutBlocks
from ..utils.free_blocks import drop_specks, ink_mask, thin_vlines
from ..utils.free_columns import block_columns, grid_columns


class ColumnTraceParams(BaseModel):
    bg_win: int = 51
    ink_ratio: float = 0.72
    pitch_min: int = 80            # 列距搜索范围（px，原图尺度）
    pitch_max: int = 300
    seam_band: float = 0.18        # 变缝能偏离直线的幅度（× 列宽）
    sample_step: int = 4           # 缝落盘的采样行距
    min_speck: int = 15            # 面积小于此的墨点先去掉
    pitch_prior: float | None = None   # 全册列距先验（px）；人标的 pitch 优先
    grid: bool = True              # 有列距先验或人标列数时走等宽网格
    grid_reg: float = 4.0          # 列宽偏离列距的罚
    grid_cover: float = 1.0        # 网格外剩下的墨（按列计）的罚
    grid_line_bonus: float = 3.0   # 细竖线（浅界行）处切线的奖励
    grid_seam_band: float = 0.08   # 内部切线变缝的幅度（× 列距）
    spine_margin: int = 150        # 版心线没探到时，书脊一侧这么宽的墨不要求被网格盖住


@register_step
class ColumnTraceStep(Step):
    spec = StepSpec(
        id="column_trace", title="Step2 块内找列（自由版式）", version="1.1", unit="page",
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
        gray = ctx.raw_page(page)
        ink = drop_specks(ink_mask(gray, p.bg_win, p.ink_ratio), p.min_speck)
        lines = None
        col_no = 0
        for b in todo:
            x0, y0, x1, y1 = (int(round(v)) for v in bbox_tr_to_tl(b.box, W))
            x0, y0 = max(0, x0), max(0, y0)
            sub = ink[y0:y1, x0:x1]
            if sub.size == 0 or not sub.any():
                continue
            pitch = b.pitch_hint or p.pitch_prior
            if p.grid and (pitch or b.cols_hint):
                if lines is None:
                    lines = thin_vlines(gray, p.bg_win)
                # 版心线没探到、块又贴着书脊那侧：那边的墨可能是版心
                spine = lb.spine if (lb.spine and lb.banxin is None) else None
                bc = grid_columns(sub, lines[y0:y1, x0:x1], pitch=pitch, n=b.cols_hint, spine=spine,
                                  spine_margin=p.spine_margin, line_bonus=p.grid_line_bonus,
                                  reg=p.grid_reg, cover=p.grid_cover, seam_band=p.grid_seam_band)
            else:
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
