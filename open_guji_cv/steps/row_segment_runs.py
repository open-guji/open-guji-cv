"""Step3（现代印刷链）单列切分：墨段 + 字身盒模型 DP → 带类型的项（char / punct / blank）。

顶替刻本链的 `row_segment`（固定 N 格弹性 DP）：现代排印本每列项数不定、标点挤压、
字距随列调整，前提不成立（见 `utils/run_segment.py` 模块头）。产同一种 `cells`——
`slot`/`pos` 从 1 起连续编号、`n_body_slots` = 本列实际项数；`kind` 多了 `punct`；
不出折线缝、不出多候选切点（现代字间是纸，切点没有歧义）。Step4 `cell_shrink`
原样复用。
"""

from __future__ import annotations

from pydantic import BaseModel

from ..core.spec import StepSpec, column_key
from ..core.step import RunContext, Step, register_step
from ..products.kinds.cells import CellRec, ColumnCells, PageCells
from ..products.kinds.columns import PageWindows
from ..products.kinds.gate import GateManifest
from ..utils.run_segment import segment_column_runs
from ._warpmap import ColumnMapper


class RowSegmentRunsParams(BaseModel):
    ink_threshold: int = 128
    only_admitted: bool = True
    blank_min_frac: float = 0.8      # 首尾空出 ≥ 此 × em 才记一个 blank 项
    small_char_frac: float = 0.8     # 字高 < 此 × em 标 small
    extend_max_frac: float = 0.6     # 首末项向外最多扩多少 em
    #: **刚性网格模式**（三模式方案 §四.2）。两本现代书版式相反，所以这是开关不是路：
    #: 北行日錄（竖排）标点挤压撑满、字距逐列变 → 默认 False，逐列估 pitch；
    #: 考補萃編（横排）全角方格、pitch 跨页 σ<1px → True，pitch 锁页级常量不逐列估。
    #: 开了才有意义的前提是 `pitch_hint` 给得准（册配置 `pitch_prior` 或页级中位）。
    rigid: bool = False
    rigid_weight: float = 3.0        # 刚性时 char→char 转移代价的倍率
    #: **项内空格位**：项与项之间的墨缝能装下整格时补 `blank` 项。
    #: 默认关（北行日錄撑满排版，列内没有真空格）；方格排版的书要开——
    #: 空格是「著者 ∥ 書名」的分隔符，吞掉就丢结构，还会被误记成漏切。
    interior_blank: bool = False
    blank_gap_frac: float = 0.55     # 墨缝 ≥ 此 × pitch 才考虑补空格位


@register_step
class RowSegmentRunsStep(Step):
    spec = StepSpec(
        id="row_segment_runs", title="Step3 单列切分（墨段盒模型，现代印刷）", version="1.1",
        unit="column",
        consumes=("gate_manifest", "column_windows", "column_image", "line_index"), produces=("cells",),
        params=RowSegmentRunsParams,
        code_deps=("open_guji_cv.utils.run_segment",),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: RowSegmentRunsParams = ctx.params_for(self)  # type: ignore[assignment]
        gate: GateManifest = ctx.product("gate_manifest", page)
        wins: PageWindows = ctx.product("column_windows", page)
        page_w = wins.page_size[0]
        out: list[ColumnCells] = []
        # 两遍法：先让每列自估字身 em 与字距 pitch，取本页中位当页级值；再把页级值当 hint
        # 把**每一列**重切一遍——短列（「二月」这种只有两三个墨段的）自估不出来、小字多的
        # 列自估偏小，都靠页级值兜底。页级 em / pitch 是排版常量（同一书同一字号），比列自估稳。
        def _seg(gc, em_hint, pitch_hint):
            img = ctx.image("column_image", column_key(page, gc.col))
            return segment_column_runs(
                img, content_x=gc.content_x, border_top=gc.border_top,
                border_bottom=gc.border_bottom, ink_threshold=p.ink_threshold,
                em_hint=em_hint, pitch_hint=pitch_hint,
                blank_min_frac=p.blank_min_frac,
                small_char_frac=p.small_char_frac, extend_max_frac=p.extend_max_frac,
                rigid=p.rigid, rigid_weight=p.rigid_weight,
                interior_blank=p.interior_blank, blank_gap_frac=p.blank_gap_frac)

        # 小字整列（脚注列，line_index 标 small_col）字号本来就小，不拿页级 em/pitch 去套；
        # 页级值也不从它们身上取
        li = ctx.product("line_index", page)
        small_cols = {ln.col for ln in li.lines if "small_col" in ln.flags}
        admitted = [gc for gc in gate.columns if gc.admitted or not p.only_admitted]
        first = {gc.col: _seg(gc, None, None) for gc in admitted}
        good = [r for c, r in first.items()
                if r is not None and r.n_runs_total >= 6 and c not in small_cols]
        page_em = float(sorted(r.em for r in good)[len(good) // 2]) if good else None
        page_pitch = (float(sorted(r.pitch for r in good)[len(good) // 2]) if good
                      else ctx.book.pitch_prior)
        for gc in gate.columns:
            base = dict(col=gc.col, n_raised=0, period=gate.period, ref_w=gate.ref_w,
                        content_x=gc.content_x, border_top=gc.border_top,
                        border_bottom=gc.border_bottom, top_slack=0.0)
            if p.only_admitted and not gc.admitted:
                out.append(ColumnCells(ok=False, n_body_slots=0,
                                       error="未过交接闸: " + "; ".join(gc.reject), **base))
                continue
            r = first[gc.col]
            if r is not None and page_em and gc.col not in small_cols:
                r = _seg(gc, page_em, page_pitch)
            wrec = wins.column(gc.col)
            mapper = None
            if wrec is not None:
                mapper = ColumnMapper(page_w, wrec.left_line.to_vline(), wrec.right_line.to_vline(),
                                      wrec.top_y, wrec.bottom_y)
            if r is None:
                out.append(ColumnCells(ok=True, n_body_slots=0, cells=[], boundaries=[],
                                       flags=["empty"], **base))
                continue
            x0, x1 = gc.content_x
            cells: list[CellRec] = []
            for i, c in enumerate(r.cells):
                slot = i + 1
                cells.append(CellRec(
                    slot=slot, pos=slot, y0=float(c.y0), y1=float(c.y1),
                    x0=float(x0), x1=float(x1), kind=c.kind, sub=None, order=i,
                    ink_ratio=float(c.ink_ratio), raised=False, flags=list(c.flags),
                    quad_page=(None if mapper is None else
                               [(round(x, 2), round(y, 2)) for x, y in mapper.quad_tr(x0, c.y0, x1, c.y1)]),
                ))
            out.append(ColumnCells(ok=True, n_body_slots=len(cells),
                                   boundaries=[float(b) for b in r.boundaries], cells=cells,
                                   em=float(r.em), pitch=float(r.pitch), flags=list(r.flags),
                                   **base))
        return {"cells": PageCells(page=page, period=gate.period, ref_w=gate.ref_w, columns=out)}
