"""Step3 → Step4 交接闸：把「DP 有解、格数没有异常偏离」的列推给 Step4；
R2/R2s 只标记不拦（图像极限，不算错，见 `eval/rulers.py` 模块头）。

判据来自 `.claude/doc/交接闸/02-补闸3与闸4.md`（原卡）与
`Step3-逐字切分/任务书-补闸3.md`（拆出的任务书），但**任务书自己标黄警告
"格数=版式格数"这条描述没验证过**：`segment_column` 的 `n_body_slots` 是
DP 的输入约束不是输出结果，不满足时已经直接体现为 `ok=False`（即 L1 第
一条），不是一个独立可判定的失败态。核实后真正能落地的第二条判据是
`n_body_slots`（列级实际值，由 `utils.row_boundaries.effective_body_slots`
算，可能因版框装不下正当下调一格）与版式格数的偏离：等于或差 1 都正常，
差 2 格以上说明探测/计算本身出了问题（不是正当下调），才该拦。

判据分两层：
- **L1 列级 block**：`ok=False`（DP 无解）；`n_body_slots` 与版式格数偏离
  超过 1 格（超出 `effective_body_slots` 能正当下调的范围）；
- **L2 列级 flag（不 block）**：R2 可改善格线数 > 0；R2s 真粘连格线存在——
  两者都只写进 `flags`，`admitted` 不受影响，因为原卡与任务书都明确写
  "flag，不算错，这是图像极限"。

R2/R2s/R2x 的判据必须与 `eval/rulers.py` 算的是同一个量——两处共用
`eval.rulers.classify_boundary`，不再各写一份（Step0 闸 0 曾经栽在
"文档说的量"和"代码实际算的量"对不上）。
"""

from __future__ import annotations

from pydantic import BaseModel

from ..core.spec import GateLevel, GateSpec, StepSpec
from ..core.step import RunContext, Step, attach_gate, register_step
from ..eval.rulers import _col_profile, classify_boundary
from ..products.kinds.cells import PageCells
from ..products.kinds.row_segment_gate import RowSegmentGateColumn, RowSegmentGateManifest


class RowSegmentGateParams(BaseModel):
    expected_slots: int | None = None   # None = Book.chars_per_line
    slot_tol: int = 1                   # n_body_slots 与版式格数的容许偏差
                                         # （effective_body_slots 正当下调 1 格）


@register_step
class RowSegmentGateStep(Step):
    spec = StepSpec(
        id="row_segment_gate", title="Step3→4 交接闸", version="1.0", unit="column",
        consumes=("cells",), produces=("row_segment_gate_manifest",),
        params=RowSegmentGateParams,
        code_deps=("open_guji_cv.eval.rulers",),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: RowSegmentGateParams = ctx.params_for(self)  # type: ignore[assignment]
        expected = p.expected_slots or ctx.book.chars_per_line
        if not ctx.has_product("cells", page):
            return {"row_segment_gate_manifest": RowSegmentGateManifest(
                page=page, admitted=False, reject=["L1：上游 cells 产物缺失"])}
        cells: PageCells = ctx.product("cells", page)

        recs: list[RowSegmentGateColumn] = []
        for cc in cells.columns:
            reject: list[str] = []
            flags: list[str] = []
            if not cc.ok:
                reject.append(f"L1：DP 无解（{cc.error or '未知原因'}）")
            elif expected is not None and abs(cc.n_body_slots - expected) > p.slot_tol:
                reject.append(
                    f"L1：格数 {cc.n_body_slots} 偏离版式格数 {expected} "
                    f"超过容许的 {p.slot_tol} 格（非 effective_body_slots 的正当下调）")

            n_r2 = n_r2s = n_r2x = 0
            if not reject and cc.ok:
                # 与 eval/rulers.py 用同一个函数取墨投影——两处必须是同一个量。
                prof = _col_profile(ctx.store, ctx.book.id, page, cc.col)
                if prof is not None:
                    for b in cc.boundaries[1:-1]:
                        result = classify_boundary(prof, int(round(b)), cc.period or 40)
                        if result is None:
                            continue
                        cls, _, _ = result
                        if cls == "r2":
                            n_r2 += 1
                        elif cls == "r2x":
                            n_r2x += 1
                        elif cls == "r2s":
                            n_r2s += 1
                if n_r2:
                    flags.append(f"L2：{n_r2} 条格线可改善（R2），未修")
                if n_r2s:
                    flags.append(f"L2：{n_r2s} 条格线真粘连（R2s），图像极限，flag 不算错")

            recs.append(RowSegmentGateColumn(
                col=cc.col, admitted=not reject, reject=reject, flags=flags,
                n_body_slots=cc.n_body_slots if cc.ok else None,
                n_r2=n_r2, n_r2s=n_r2s, n_r2x=n_r2x,
            ))

        page_admitted = any(c.admitted for c in recs) if recs else False
        page_reject = [] if recs else ["L1：本页无 cells 记录"]
        return {"row_segment_gate_manifest": RowSegmentGateManifest(
            page=page, admitted=page_admitted, reject=page_reject, columns=recs)}


# 挂到 Step3（row_segment）出口——levels 的 desc 只描述层次，不重复具体阈值数字
# （阈值在 RowSegmentGateParams 里，写两处会漂）。
attach_gate("row_segment", GateSpec(
    id="row_segment_gate", unit="column", on_fail="block",
    levels=(
        GateLevel(id="L1", unit="column", desc="DP 是否有解"),
        GateLevel(id="L1", unit="column",
                  desc="格数是否偏离版式格数超过容许范围（非 effective_body_slots 的正当下调）"),
        GateLevel(id="L2", unit="column",
                  desc="R2 可改善格线数——flag，不拦（该修但不算作废这一列）"),
        GateLevel(id="L2", unit="column",
                  desc="R2s 真粘连格线数——flag，不拦（图像极限，不算错）"),
    ),
))
