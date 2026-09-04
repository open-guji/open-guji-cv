"""Step2 → Step3 交接闸：只把「确实是一列、且过了闸」的列推给 Step3。

判据分三层：
- **L1 页级**（只看几何）：探出的列数 = 版式列数。整页性的问题才放这里；
- **L1c 列级**：本列宽偏离本页中位数超 ±15% —— 多半是把界行圈进了列窗。
  ⚠️ 这条**原先错放在页级**，一列坏就整页作废（vol01/42 八列完好只因 c9 坏而全废，
  vol02 全书 27 页被拦、其中 17 页只坏 c1 一列）。2026-09-03 改为列级；
- **L2 列级**：两侧外 25% 最低墨占比 <= 0.045（已知几乎没有独立筛选力，只挡极端）；
- **L3 金标**：P0 不接（tier=gate）。

页级共享量 period / ref_w 用**几何正常的列**算（剔掉 L1c 命中的列）——那些列的
投影带着一条整界行，不该参与共识。实测剔掉后 period 变化 ≤1.5、ref_w ≤5px。
若正常列不足半数则整页拒绝，因为共识已无意义。
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
    "border_top / border_bottom 沿用 windows 的 *_in_column；抬头列 top_slack = border_top，"
    "顶格列（版框平齐但顶端有字墨）top_slack = 0.5×period",
    "n_raised 不给：raised 只是几何标记，由 Step3 参数按版式先验定",
]


class ColumnGateParams(BaseModel):
    expected_cols: int | None = None    # None = Book.expected_cols
    width_tol: float = 0.15
    side_floor_max: float = 0.045
    tier: str = "gate"                  # gate | gold（gold 需接数据集，P2）
    ink_threshold: int = 128
    bottom_slack: float = 16.0     # 下界在版框线之外再放多少，见 border_bottom 注释


@register_step
class ColumnGateStep(Step):
    spec = StepSpec(
        id="column_gate", title="Step2→3 交接闸", version="1.2", unit="column",
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

        # **列宽偏离是列级判据，不是页级**（2026-09-03 改）。
        # 它逐列算得出，却曾被放在页级拒因里 → 一列坏就整页 9 列作废。
        # 实证：vol01/42 的 c1~c8 偏离都 ≤3.7%、外缘墨 ≤0.008（完好），只有 c9
        # 残留了一条斜界行（宽 +16.6%、外缘墨 0.092），结果 9 列全废。
        # vol02 全书 27 页因它被拦，其中 17 页只坏 c1 一列。
        # 见 doc/step3_error_survey.md 乙类。
        wide_cols = {c.col: (w - med_w) / med_w
                     for c, w in zip(cols, widths)
                     if med_w and abs(w - med_w) > p.width_tol * med_w}

        # 逐列：页级先验要用**几何正常的列**算。
        # 宽度异常的列多半是把界行圈进了列窗，它的投影带着一条整线，
        # 不该参与页级周期/列距的共识。实测剔掉后 period 变化 ≤1.5、ref_w ≤5px。
        projs, borders, dst_ws, band_ws = [], [], [], []
        for c in cols:
            cleaned = ctx.image("column_image", column_key(page, c.col))
            b0, b1 = c.band
            if c.col in wide_cols:
                continue
            projs.append(row_ink_projection(cleaned, b0, b1, ink_threshold=p.ink_threshold))
            borders.append((c.border_top_in_column, c.border_bottom_in_column))
            dst_ws.append(b1 - b0)
            band_ws.append(float(b1 - b0))

        period = ref_w = None
        if not page_reject:
            if len(projs) < max(2, expected // 2):
                page_reject.append(
                    f"L1：几何正常的列只剩 {len(projs)} 条，不足以定页级先验")
            else:
                try:
                    period = round(float(estimate_shared_period(projs, borders, dst_ws)), 2)
                except ValueError as e:
                    page_reject.append(f"L1：页级周期估不出来（{e}）")
                ref_w = float(statistics.median(band_ws)) if band_ws else None
        page_ok = not page_reject

        # **顶格列也要 top_slack**（2026-09-03 加）。原先只有 `raised`（Step1 探到
        # 抬头**框**、版框有台阶）的列才给，可这批书里更常见的是**版框平齐、字从
        # 版框内顶端起写**的顶格列——`raised=False`、`border_top_in_column=0`，
        # 于是 `top_slack=0`，DP 的首锚点窗口开不上去，首字被压在格顶。
        # 实测 dev_set 7 条格数不足的列里 5 条是这一型（vol01/141c7「諭旨」、
        # 26c2、42c2、vol02/3c3、3c4），给 n_raised=1 也修不好——格数够了但
        # 首锚点仍卡在原处；只有 33c8（真抬头框，top_slack=148）能修。
        # 判据：列图**最顶端一格高之内**就有字墨（顶格写的字必然贴着版框），
        # 且这段墨不是版框线残留（`clean_column` 已抹掉版框，所以剩下的就是字）。
        # 给的量是「墨起点之上留半格」——够 DP 把首字整个圈进来，又不至于把
        # 窗口开到无边（开过头的代价实测很小，见 row_boundaries 的 top_slack 说明）。
        top_ink_slack: dict[int, float] = {}
        if page_ok and period:
            probe = max(20, int(round(period * 0.6)))
            for c in cols:
                if c.raised or c.border_top_in_column > 1.0:
                    continue                      # 真抬头列走原路
                try:
                    img = ctx.image("column_image", column_key(page, c.col))
                except Exception:
                    continue
                b0, b1 = c.band
                prof = (img[:, int(b0):int(b1)] < p.ink_threshold).mean(axis=1)
                head = prof[:probe]
                if head.size and float(head.max()) > 0.08:
                    top_ink_slack[c.col] = round(float(period) * 0.5, 2)

        recs: list[GateColumn] = []
        for c in cols:
            reasons: list[str] = []
            if not page_ok:
                reasons.append("页级未过 L1")
            if c.col in wide_cols:
                reasons.append(f"L1c：本列宽 {c.warped_size[0]}px 偏离本页中位数 "
                               f"{med_w:.0f}px {wide_cols[c.col]:+.0%}（多半圈进了界行）")
            if c.side_floor > p.side_floor_max:
                reasons.append(f"L2：两侧最低墨占比 {c.side_floor:.4f} > {p.side_floor_max}")
            if p.tier == "gold":
                reasons.append("L3：金标准入尚未接入（P2）")
            recs.append(GateColumn(
                col=c.col, admitted=not reasons, reject=reasons, tier=p.tier,
                content_x=(float(c.band[0]), float(c.band[1])),
                border_top=float(c.border_top_in_column),
                # **下界给列图底部，不是版框线**（2026-09-03 改，A4）。
                # Step3 的 candN 窗口是 `[border_bottom - 0.3·period, border_bottom]`，
                # 上界就是这个值——传版框线的话，末字只要压着版框写，末边界就
                # **永远够不到它**。实测 dev_set 216 列：真末墨超出 border_bottom
                # 的有 147 列（68%），末格 y1 比真末墨低中位 11px、27.6% 的列低
                # 超过 20px，于是末字下半落在第 21 格之外——slot 21 占了 R4
                # 被切总数的 57%（36/63）。
                # 放 16px 是扫出来的最优点（dev_set，末墨超出 / R2 可改善）：
                #    0px  27.6% / 0.40%     16px   9.6% / **0.20%**
                #    8px  16.7% / 0.28%     24px   7.1% / 0.25%
                #   40px（放到列图底） 1.5% / 0.76% ← 过冲，解空间一松反而多切在字上
                # 16 同时让末墨超出降到 9.6% 且 R2 降到最低，代价只是多 1 列无解。
                # 版框线本身已由 `clean_column` 抹白，不会被当成墨。
                border_bottom=float(min(c.warped_size[1],
                                        c.border_bottom_in_column + p.bottom_slack)),
                top_slack=(float(c.border_top_in_column) if c.raised
                           else top_ink_slack.get(c.col, 0.0)),
                raised=c.raised, head_raise_inner_y=c.head_raise_inner_y,
                warped_size=c.warped_size, side_floor=c.side_floor,
                band_width=float(c.band[1] - c.band[0]),
            ))
        return {"gate_manifest": GateManifest(
            page=page, admitted=page_ok, reject=page_reject, period=period, ref_w=ref_w,
            column_widths=widths, median_width=med_w, columns=recs, contract=CONTRACT)}
