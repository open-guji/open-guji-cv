"""Step3 单列文字切分：清理后列图 → 带类型的字格 + 读序。

包的是 `utils/row_boundaries.segment_column`。输入参数全部来自交接闸（页级 period / ref_w，
列级 content_x / border_top / border_bottom / top_slack）；n_body_slots 来自 Book / 参数。
产物坐标是列图坐标，另带经 Step2 逆映射回原图的 quad_page（规范空间）。
"""

from __future__ import annotations

from pydantic import BaseModel

from ..core.spec import StepSpec, column_key
from ..core.step import RunContext, Step, register_step
from ..products.kinds.cells import CellRec, ColumnCells, PageCells
from ..products.kinds.columns import PageWindows
from ..products.kinds.gate import GateManifest
from ..utils.row_boundaries import segment_column
from ._warpmap import ColumnMapper


class RowSegmentParams(BaseModel):
    n_body_slots: int | None = None      # None = Book.chars_per_line
    n_raised: int = 0                    # 抬头多出的格数；版式先验，raised 不自动推
    ink_threshold: int = 128
    min_ink_ratio: float = 0.01
    raise_tol: float = 2.0
    detect_jiazhu: bool = True
    only_admitted: bool = True           # 只切过闸的列


@register_step
class RowSegmentStep(Step):
    spec = StepSpec(
        id="row_segment", title="Step3 单列文字切分", version="1.1", unit="column",
        consumes=("gate_manifest", "column_windows", "column_image"), produces=("cells",),
        params=RowSegmentParams,
        code_deps=("open_guji_cv.utils.row_boundaries", "open_guji_cv.utils.jiazhu_split",
                   "open_guji_cv.utils.column_projection"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: RowSegmentParams = ctx.params_for(self)  # type: ignore[assignment]
        n_body = p.n_body_slots or ctx.book.chars_per_line
        gate: GateManifest = ctx.product("gate_manifest", page)
        wins: PageWindows = ctx.product("column_windows", page)
        page_w = wins.page_size[0]
        out: list[ColumnCells] = []
        for gc in gate.columns:
            base = dict(col=gc.col, n_body_slots=n_body, n_raised=p.n_raised,
                        period=gate.period, ref_w=gate.ref_w, content_x=gc.content_x,
                        border_top=gc.border_top, border_bottom=gc.border_bottom,
                        top_slack=gc.top_slack)
            if p.only_admitted and not gc.admitted:
                out.append(ColumnCells(ok=False, error="未过交接闸: " + "; ".join(gc.reject), **base))
                continue
            if gate.period is None:
                out.append(ColumnCells(ok=False, error="页级 period 缺失", **base))
                continue
            img = ctx.image("column_image", column_key(page, gc.col))
            r = segment_column(
                img, period=gate.period, n_body_slots=n_body, n_raised=p.n_raised,
                border_top=gc.border_top, border_bottom=gc.border_bottom, ref_w=gate.ref_w,
                top_slack=gc.top_slack, content_x=gc.content_x,
                ink_threshold=p.ink_threshold, min_ink_ratio=p.min_ink_ratio,
                raise_tol=p.raise_tol, detect_jiazhu=p.detect_jiazhu)
            if r is None:
                out.append(ColumnCells(ok=False, error="弹性 DP 无解", **base))
                continue
            wrec = wins.column(gc.col)
            mapper = None
            if wrec is not None:
                mapper = ColumnMapper(page_w, wrec.left_line.to_vline(), wrec.right_line.to_vline(),
                                      wrec.top_y, wrec.bottom_y)
            n_total = n_body + p.n_raised
            cells = []
            for c in r.cells:
                pos = _slot_to_pos(c.slot, p.n_raised)
                if not 1 <= pos <= n_total:
                    raise ValueError(f"slot {c.slot} 换算出的物理位置 {pos} 越界（总格数 {n_total}）")
                cells.append(CellRec(
                    slot=c.slot, pos=pos, y0=float(c.y0), y1=float(c.y1),
                    x0=float(c.x0), x1=float(c.x1), kind=c.kind, sub=c.sub, order=int(c.order),
                    gap_center=None if c.gap_center is None else float(c.gap_center),
                    ink_ratio=float(c.ink_ratio), raised=bool(c.raised),
                    quad_page=(None if mapper is None else
                               [(round(x, 2), round(y, 2)) for x, y in mapper.quad_tr(c.x0, c.y0, c.x1, c.y1)]),
                ))
            out.append(ColumnCells(ok=True, boundaries=[float(b) for b in r.boundaries],
                                   cells=cells, **base))
        return {"cells": PageCells(page=page, period=gate.period, ref_w=gate.ref_w, columns=out)}


def _slot_to_pos(slot: int, n_raised: int) -> int:
    """对外 slot（正文 1..n，抬头 -n_raised..-1，跳 0）→ 1 起的物理位置。"""
    return slot + n_raised + 1 if slot < 0 else slot + n_raised
