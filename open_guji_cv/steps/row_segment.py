"""Step3 单列文字切分：清理后列图 → 带类型的字格 + 读序。

包的是 `utils/row_boundaries.segment_column`。输入参数全部来自交接闸（页级 period / ref_w，
列级 content_x / border_top / border_bottom / top_slack）；n_body_slots 来自 Book / 参数。
产物坐标是列图坐标，另带经 Step2 逆映射回原图的 quad_page（规范空间）。
"""

from __future__ import annotations

from pydantic import BaseModel, model_validator

from ..core.spec import StepSpec, column_key
from ..core.step import RunContext, Step, register_step
from ..products.kinds.cells import CellRec, ColumnCells, CutPointCandidates, PageCells, SeamCandidate
from ..products.kinds.columns import PageWindows
from ..products.kinds.gate import GateManifest
from ..utils.cut_select import ckpt_fingerprint, get_judge
from ..utils.row_boundaries import (NONUNIFORM_LAM, effective_body_slots,
                                    segment_column)
from ._warpmap import ColumnMapper


class RowSegmentParams(BaseModel):
    n_body_slots: int | None = None      # None = Book.chars_per_line
    n_raised: int = 0                    # 抬头多出的格数；版式先验，raised 不自动推
    ink_threshold: int = 128
    min_ink_ratio: float = 0.01
    raise_tol: float = 2.0
    detect_jiazhu: bool = True
    only_admitted: bool = True           # 只切过闸的列
    seam_band: int = 20                  # 折线切分走廊半宽；0 = 关（utils/seam.py）
    cut_judge: str = "unet"              # 候选池裁判：unet（utils/cut_select.py，2026-09-14 起现役）| rule（只用旧规则）
    judge_fingerprint: str = ""          # 裁判权重指纹，自动填（进 Step 指纹：换权重 → Step3 产物自动 stale）

    @model_validator(mode="after")
    def _fill_judge_fingerprint(self):
        # 与 glyph_match.GlyphMatchParams.db_fingerprint 同一套路：模型是外部可变状态，
        # 不进指纹的话换了权重产物还显示 fresh。权重缺失时为空串 → 与裁判可用时指纹不同。
        if self.cut_judge == "unet" and not self.judge_fingerprint:
            object.__setattr__(self, "judge_fingerprint", ckpt_fingerprint())
        return self


@register_step
class RowSegmentStep(Step):
    spec = StepSpec(
        id="row_segment", title="Step3 单列文字切分", version="1.11", unit="column",   # 1.11：單行小注自成 kind=jiazhu_solo（此前借 jiazhu_a 的壳）
        consumes=("gate_manifest", "column_windows", "column_image"), produces=("cells",),
        params=RowSegmentParams,
        code_deps=("open_guji_cv.utils.row_boundaries", "open_guji_cv.utils.jiazhu_split",
                   "open_guji_cv.utils.column_projection", "open_guji_cv.utils.seam",
                   "open_guji_cv.utils.cut_select"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: RowSegmentParams = ctx.params_for(self)  # type: ignore[assignment]
        n_body = p.n_body_slots or ctx.book.chars_per_line
        gate: GateManifest = ctx.product("gate_manifest", page)
        wins: PageWindows = ctx.product("column_windows", page)
        page_w = wins.page_size[0]
        # 人裁回流：workspace 裁决表里这本书已裁决的切点（feedback/lookup.py，
        # **不读 open-guji-dataset**），按 (页,列) 筛出 slot_above → kind 传给
        # segment_column 收敛候选。裁决不进指纹，该页下次重跑才生效（见 lookup 注）。
        from ..feedback.lookup import resolved_cuts as _resolved_cuts
        from ..feedback.lookup import resolved_slots as _resolved_slots
        book_resolved = _resolved_cuts(ctx.book.id)
        # 同一条回流路径的兄弟：逐列字数覆盖（`review/slot_count_cards.py`）。
        # `chars_per_line` 是页级版式常量，DP 硬切；少数列真的比常量多/少刻了
        # 一个字时（bxgb p33c19 实测 22 字 vs 常量 21），没有可靠的几何信号能
        # 自动探测（格高/period 比值测过，两个方向都不可靠，见
        # feedback_cell_height_not_merge_signal），只能人核对后写回。
        #
        # 同一条裁决还带 `uniform`（2026-09-20）：字数对了不等于**字距**均匀。
        # p33c19 就是字数 22 给对了、DP 仍把首字「尉」劈成两格——等距先验比
        # 墨量判据贵五倍（账见 row_boundaries.NONUNIFORM_LAM）。标了非均匀的列
        # 把 lam 降下来，其余列一字不动。
        book_slots = _resolved_slots(ctx.book.id)
        # 候选池裁判（U-Net，进程内单例）；权重/torch 不可用时为 None → segment_column 按旧规则走
        judge = get_judge() if p.cut_judge == "unet" else None
        out: list[ColumnCells] = []
        for gc in gate.columns:
            # 逐列格数：页级参数与闸给的 hint 取大者。hint 是「这一列墨跨度
            # 装得下几个字」（见 GateColumn.n_raised_hint）——同一页上有的抬头列
            # 多一格、有的不多，页级参数给不出这个差别，DP 只能丢掉首字。
            n_raised_col = max(p.n_raised, getattr(gc, "n_raised_hint", 0) or 0)
            # 版框装不下 n_body 格的页（vol01/5 只有 20 行）按实际行数切，见
            # row_boundaries.effective_body_slots
            n_body_col = effective_body_slots(n_body, gc.border_top, gc.border_bottom, gate.period)
            # 人裁逐列字数覆盖优先于上面两条自动判据——人是终审，跟
            # `_apply_resolved_cut` 里"人裁收敛成功就不再是升级"同一条纪律。
            slot_override = book_slots.get((page, gc.col))
            if slot_override is not None:
                n_body_col = slot_override.n_slots
            base = dict(col=gc.col, n_body_slots=n_body_col, n_raised=n_raised_col,
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
            col_resolved = {slot: kind for (pg, col, slot), kind in book_resolved.items()
                            if pg == page and col == gc.col}
            r = segment_column(
                img, period=gate.period, n_body_slots=n_body_col, n_raised=n_raised_col,
                border_top=gc.border_top, border_bottom=gc.border_bottom, ref_w=gate.ref_w,
                top_slack=gc.top_slack, content_x=gc.content_x,
                ink_threshold=p.ink_threshold, min_ink_ratio=p.min_ink_ratio,
                raise_tol=p.raise_tol, detect_jiazhu=p.detect_jiazhu, seam_band=p.seam_band,
                resolved_cuts=col_resolved or None, cut_judge=judge,
                **({} if slot_override is None or slot_override.uniform
                   else {"lam": NONUNIFORM_LAM}))
            if r is None:
                out.append(ColumnCells(ok=False, error="弹性 DP 无解", **base))
                continue
            wrec = wins.column(gc.col)
            mapper = None
            if wrec is not None:
                mapper = ColumnMapper(page_w, wrec.left_line.to_vline(), wrec.right_line.to_vline(),
                                      wrec.top_y, wrec.bottom_y)
            n_total = n_body_col + n_raised_col
            cells = []
            for c in r.cells:
                pos = _slot_to_pos(c.slot, n_raised_col)
                if not 1 <= pos <= n_total:
                    raise ValueError(f"slot {c.slot} 换算出的物理位置 {pos} 越界（总格数 {n_total}）")
                cells.append(CellRec(
                    slot=c.slot, pos=pos, y0=float(c.y0), y1=float(c.y1),
                    x0=float(c.x0), x1=float(c.x1), kind=c.kind, sub=c.sub, order=int(c.order),
                    gap_center=None if c.gap_center is None else float(c.gap_center),
                    ink_ratio=float(c.ink_ratio), raised=bool(c.raised),
                    suspect_jiazhu_body=bool(getattr(c, "suspect_jiazhu_body", False)),
                    seam_top=c.seam_top, seam_bottom=c.seam_bottom,
                    quad_page=(None if mapper is None else
                               [(round(x, 2), round(y, 2)) for x, y in mapper.quad_tr(c.x0, c.y0, c.x1, c.y1)]),
                ))
            out.append(ColumnCells(ok=True, boundaries=[float(b) for b in r.boundaries],
                                   cells=cells, cut_candidates=[
                                       CutPointCandidates(
                                           k=cp.k, y=cp.y, slot_above=cp.slot_above,
                                           slot_below=cp.slot_below, chosen=cp.chosen,
                                           chosen_by=cp.chosen_by,
                                           escalate=cp.escalate, escalate_reason=cp.escalate_reason,
                                           origin=cp.origin,
                                           candidates=[SeamCandidate(
                                               kind=c.kind, y=c.y, seam_ink=c.seam_ink,
                                               dev_max=c.dev_max, agree=c.agree, dis_unet=c.dis_unet)
                                               for c in cp.candidates],
                                       ) for cp in r.cut_candidates],
                                   **base))
        return {"cells": PageCells(page=page, period=gate.period, ref_w=gate.ref_w, columns=out)}


def _slot_to_pos(slot: int, n_raised: int) -> int:
    """对外 slot（正文 1..n，抬头 -n_raised..-1，跳 0）→ 1 起的物理位置。"""
    return slot + n_raised + 1 if slot < 0 else slot + n_raised
