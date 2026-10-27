"""自由版式 Step2：文字块 → 列（左右是弯缝，`free_columns`）。

有列距先验（人标 `pitch`，或参数 `pitch_prior`）或人标列数时走等宽网格（`grid_columns`）：
浅界行当好切线、列宽贴近列距、网格两端浮动但要盖住正文的墨（版心不算）。
都没有时退回自估：剪切校斜、投影自相关估列距、DP 定列界直线、带内走最省墨竖缝；
块里有竖线（界行、表格线）就先按竖线分段。
有界栏但不规律的正文块（人标 `ruled: true`，1.2 起；yxat 99–102 下栏）：也走网格，但列数不给死、列宽放宽到
0.5–1.2 倍列距（列宽不齐、常几列合一列，标题列窄），网格外漏的墨罚得重（不漏掉标题列）；每列再找横界栏，
记成 `breaks`，Step3 遇到就断开切字。
1.3 起（Sheldon 10-27 审 yxat 9–16 页）：网格两端就是块边（版框内沿、版心线，本书左右不留白），
列宽 ≈ 块宽 ÷ 列数；人标 `align` 同组的块（上下几栏列线本来对齐）摞起来一起拟合一套网格，再各自走缝。
1.4 起（Sheldon 第二轮：「以不穿墨、穿过空白的中心作为最重要的原则」，各栏列线不一定一致）：切线代价先数
劈开几个墨块（字、框），再奖励落在空白正中，列宽放宽到 0.6–1.5 倍列距、宽窄的罚 4→1；竖线要贯穿块高 80%
才当界行（标题框边不算，免得切线贴着框边走进框里）。
算法在 `utils/free_columns.py`。
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from ..core.anchor import bbox_tr_to_tl, x_tl_to_tr, x_tr_to_tl
from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.free_layout import BlockColumnsRec, ColumnRec, FreeColumns, LayoutBlocks
from ..utils.free_blocks import drop_specks, ink_mask, rule_hlines, thin_vlines
from ..utils.free_columns import BlockColumns, ColumnSeams, block_columns, grid_columns, rule_breaks


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
    grid_reg: float = 1.0          # 列宽偏离列距的罚（1.4 起 4→1：先不穿墨，再求均匀）
    grid_cover: float = 1.0        # 网格外剩下的墨（按列计）的罚
    grid_line_bonus: float = 3.0   # 细竖线（浅界行）处切线的奖励
    grid_seam_band: float = 0.08   # 内部切线变缝的幅度（× 列距）
    spine_margin: int = 150        # 版心线没探到时，书脊一侧这么宽的墨不要求被网格盖住
    ruled_width: tuple[float, float] = (0.5, 1.2)   # ruled 块的列宽上下限（× 列距）
    ruled_reg: float = 4.0         # ruled 块列宽偏离列距的罚
    ruled_cover: float = 3.0       # ruled 块网格外漏墨的罚（标题列墨少，罚轻了会被丢在网格外）
    break_frac: float = 0.5        # 横界栏盖住列宽这么多才算断开处
    break_inset: int = 8           # 量横界栏时列两边各让进这么多（别量到竖界栏）
    grid_fixed_ends: bool = True   # 网格两端就是块边（版心线没探到、块贴书脊那侧时仍浮动）
    grid_cross: float = 1.0        # 正文网格：切线劈开一个墨块（字、框）的罚（最多计 2 个）
    grid_center: float = 0.5       # 正文网格：切线落在空白正中的奖励
    grid_width: tuple[float, float] = (0.6, 1.5)   # 正文网格列宽上下限（× 列距；标题框列宽、两行小注列窄）
    grid_rule_min: float = 0.8     # 正文网格：竖线盖住块高这么多才当界行（标题框边不算）


@register_step
class ColumnTraceStep(Step):
    spec = StepSpec(
        id="column_trace", title="Step2 块内找列（自由版式）", version="1.4", unit="page",
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
        lines = hrules = None
        boxes = {b.index: tuple(int(round(v)) for v in bbox_tr_to_tl(b.box, W)) for b in todo}
        found: dict[int, tuple[BlockColumns, bool]] = {}
        # 版心线没探到、块又贴着书脊那侧：那边的墨可能是版心
        spine = lb.spine if (lb.spine and lb.banxin is None) else None

        def grid(sub, ln, pitch, n):
            return grid_columns(sub, ln, pitch=pitch, n=n, spine=spine, spine_margin=p.spine_margin,
                                line_bonus=p.grid_line_bonus, reg=p.grid_reg, cover=p.grid_cover,
                                seam_band=p.grid_seam_band, width=p.grid_width, rule_min=p.grid_rule_min,
                                fixed_ends=p.grid_fixed_ends and spine is None,
                                cross=p.grid_cross, center=p.grid_center)

        for b in todo:
            if b.index in found:
                continue
            x0, y0, x1, y1 = boxes[b.index]
            x0, y0 = max(0, x0), max(0, y0)
            sub = ink[y0:y1, x0:x1]
            if sub.size == 0 or not sub.any():
                continue
            pitch = b.pitch_hint or p.pitch_prior
            # ruled：人给的列数只当列距的来源（列宽不齐，硬给 n 列会切进别的列）；列距、列数都没有就照常自估
            ruled_pitch = pitch or ((x1 - x0) / b.cols_hint if b.cols_hint else None)
            ruled = b.ruled and ruled_pitch is not None
            if ruled:
                if lines is None:
                    lines = thin_vlines(gray, p.bg_win)
                if hrules is None:
                    hrules = rule_hlines(gray, p.bg_win)
                bc = grid_columns(sub, lines[y0:y1, x0:x1], pitch=ruled_pitch, n=None,
                                  line_bonus=p.grid_line_bonus, reg=p.ruled_reg, cover=p.ruled_cover,
                                  seam_band=p.grid_seam_band, width=p.ruled_width)
                bc.n_source = "ruled"
            elif p.grid and (pitch or b.cols_hint):
                if lines is None:
                    lines = thin_vlines(gray, p.bg_win)
                grp = [g for g in todo if b.align and g.align == b.align and not g.ruled]
                if len(grp) > 1:
                    # 同组摞起来拟合一套网格（左右取第一块的），再按行切回各块
                    spans = [(max(0, boxes[g.index][1]), boxes[g.index][3]) for g in grp]
                    whole = grid(np.vstack([ink[a:c, x0:x1] for a, c in spans]),
                                 np.vstack([lines[a:c, x0:x1] for a, c in spans]), pitch, b.cols_hint)
                    r = 0
                    for g, (a, c) in zip(grp, spans):
                        cols = [ColumnSeams(cs.left[r:r + c - a], cs.right[r:r + c - a]) for cs in whole.columns]
                        found[g.index] = (BlockColumns(cols, whole.shear, whole.pitch, "align", whole.alt_n), False)
                        r += c - a
                    continue
                bc = grid(sub, lines[y0:y1, x0:x1], pitch, b.cols_hint)
            else:
                vr = [x_tr_to_tl(x, W) - x0 for x in b.vrules]
                bc = block_columns(sub, b.cols_hint, vr, pitch_range=(p.pitch_min, p.pitch_max),
                                   seam_band=p.seam_band)
            found[b.index] = (bc, ruled)

        col_no = 0
        for b in todo:                               # 按读序落盘
            if b.index not in found:
                continue
            bc, ruled = found[b.index]
            x0, y0, x1, y1 = boxes[b.index]
            x0, y0 = max(0, x0), max(0, y0)
            out.blocks.append(BlockColumnsRec(block=b.index, n=len(bc.columns), n_source=bc.n_source,
                                              alt_n=bc.alt_n, pitch=bc.pitch, shear=round(bc.shear, 5)))
            rows = np.r_[np.arange(0, y1 - y0, p.sample_step), y1 - y0 - 1]
            for c in bc.columns:                     # 已是右→左
                col_no += 1
                breaks: list[float] = []
                if ruled:
                    cl, cr = int(np.median(c.left)) + x0, int(np.median(c.right)) + x0
                    breaks = [float(y) for y in rule_breaks(hrules, cl + p.break_inset, cr - p.break_inset,
                                                            y0, y1, frac=p.break_frac)]
                out.columns.append(ColumnRec(
                    col=col_no, block=b.index, y0=float(y0), y1=float(y1), step=p.sample_step,
                    right=[round(x_tl_to_tr(float(c.right[r] + x0), W), 1) for r in rows],
                    left=[round(x_tl_to_tr(float(c.left[r] + x0), W), 1) for r in rows], breaks=breaks))
        return {"free_columns": out}
