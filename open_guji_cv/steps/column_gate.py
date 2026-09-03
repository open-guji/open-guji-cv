"""Step2 → Step3 交接闸：只把「确实是一列、且过了闸」的列推给 Step3。

照抄 scripts/export_step3_input.py 的判据：
- L1 页级（只看几何）：探出的列数 = 版式列数；每列宽在本页中位数 ±15% 内；
- L2 列级：两侧外 25% 最低墨占比 <= 0.045（已知几乎没有独立筛选力，只挡极端）；
- L3 金标：P0 不接（tier=gate）。
页级共享量 period / ref_w **用该页全部列算**，不只用准入的列。
"""

from __future__ import annotations

import statistics

from pydantic import BaseModel

from ..core.spec import StepSpec, column_key
from ..core.step import RunContext, Step, register_step
from ..products.kinds.columns import PageWindows
from ..products.kinds.gate import GateColumn, GateManifest
from ..utils.row_boundaries import estimate_shared_period, row_ink_projection

CONTRACT = [
    "页级共享量 period / ref_w 用该页全部列算，不只用准入的列",
    "content_x 随图传：交出去的列图抹白不裁切，Step3 内部找不到墙",
    "border_top / border_bottom 沿用 windows 的 *_in_column；抬头列 top_slack = border_top",
    "n_raised 不给：raised 只是几何标记，由 Step3 参数按版式先验定",
]


class ColumnGateParams(BaseModel):
    expected_cols: int | None = None    # None = Book.expected_cols
    width_tol: float = 0.15
    side_floor_max: float = 0.045
    tier: str = "gate"                  # gate | gold（gold 需接数据集，P2）
    ink_threshold: int = 128


@register_step
class ColumnGateStep(Step):
    spec = StepSpec(
        id="column_gate", title="Step2→3 交接闸", version="1.0", unit="column",
        consumes=("column_windows", "column_image"), produces=("gate_manifest",),
        params=ColumnGateParams,
        code_deps=("open_guji_cv.utils.row_boundaries", "open_guji_cv.utils.column_projection"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: ColumnGateParams = ctx.params_for(self)  # type: ignore[assignment]
        expected = p.expected_cols or ctx.book.expected_cols
        wins: PageWindows = ctx.product("column_windows", page)
        cols = wins.columns
        widths = [float(c.warped_size[0]) for c in cols]
        med_w = statistics.median(widths) if widths else None
        page_reject: list[str] = []
        if len(cols) != expected:
            page_reject.append(f"L1：只探出 {len(cols)} 列（版式应为 {expected}）")
        bad_w = [c.col for c, w in zip(cols, widths) if med_w and abs(w - med_w) > p.width_tol * med_w]
        if bad_w:
            page_reject.append(f"L1：列宽偏离本页中位数 {med_w:.0f}px 超过 ±{p.width_tol:.0%} 的列 {bad_w}")

        # 逐列：页级先验要用全部列，所以不管准不准入都先算
        projs, borders, dst_ws, band_ws = [], [], [], []
        for c in cols:
            cleaned = ctx.image("column_image", column_key(page, c.col))
            b0, b1 = c.band
            projs.append(row_ink_projection(cleaned, b0, b1, ink_threshold=p.ink_threshold))
            borders.append((c.border_top_in_column, c.border_bottom_in_column))
            dst_ws.append(b1 - b0)
            band_ws.append(float(b1 - b0))

        period = ref_w = None
        if not page_reject:
            try:
                period = round(float(estimate_shared_period(projs, borders, dst_ws)), 2)
            except ValueError as e:
                page_reject.append(f"L1：页级周期估不出来（{e}）")
            ref_w = float(statistics.median(band_ws)) if band_ws else None
        page_ok = not page_reject

        recs: list[GateColumn] = []
        for c in cols:
            reasons: list[str] = []
            if not page_ok:
                reasons.append("页级未过 L1")
            if c.side_floor > p.side_floor_max:
                reasons.append(f"L2：两侧最低墨占比 {c.side_floor:.4f} > {p.side_floor_max}")
            if p.tier == "gold":
                reasons.append("L3：金标准入尚未接入（P2）")
            recs.append(GateColumn(
                col=c.col, admitted=not reasons, reject=reasons, tier=p.tier,
                content_x=(float(c.band[0]), float(c.band[1])),
                border_top=float(c.border_top_in_column),
                border_bottom=float(c.border_bottom_in_column),
                top_slack=float(c.border_top_in_column) if c.raised else 0.0,
                raised=c.raised, head_raise_inner_y=c.head_raise_inner_y,
                warped_size=c.warped_size, side_floor=c.side_floor,
                band_width=float(c.band[1] - c.band[0]),
            ))
        return {"gate_manifest": GateManifest(
            page=page, admitted=page_ok, reject=page_reject, period=period, ref_w=ref_w,
            column_widths=widths, median_width=med_w, columns=recs, contract=CONTRACT)}
