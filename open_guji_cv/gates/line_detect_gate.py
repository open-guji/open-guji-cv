"""Step1（现代印刷链 `line_detect`）→ Step2 交接闸。

产出与刻本链闸1 **同一种** `border_detect_gate_manifest`，Step2 读的字段一样
（`page_type_policy == "skip"` 时整页不套列窗口）。判据：

- **L1（block）**：一列正文都没探到——空白页 / 只有书口小字的页，`page_type=blank`、
  `policy=skip`，Step2 产出空列表、闸2 自然拒收；
- **L1b（flag）**：正文列数超过 `Book.expected_cols`（现代模式里它是**上限**，
  不是等式：末页、卷题页的列数都比满页少，只有「多了」才可疑——多半是双行小注
  的两个子列被当成了两列）；
- **L2（flag）**：有 `wide` 列（宽 > 1.35 em，并列/粘连）；
- **L3（flag）**：探到脚注列——只是提醒下游这页有非正文列，不拦。
"""

from __future__ import annotations

from pydantic import BaseModel

from ..core.spec import GateLevel, GateSpec, StepSpec
from ..core.step import RunContext, Step, attach_gate, register_step
from ..products.kinds.border_detect_gate import BorderDetectGateManifest
from ..products.kinds.line_index import LineIndex


class LineDetectGateParams(BaseModel):
    max_cols: int | None = None     # None = Book.expected_cols（上限）


@register_step
class LineDetectGateStep(Step):
    spec = StepSpec(
        id="line_detect_gate", title="Step1→2 交接闸（现代印刷）", version="1.0", unit="page",
        consumes=("line_index",), produces=("border_detect_gate_manifest",),
        params=LineDetectGateParams,
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: LineDetectGateParams = ctx.params_for(self)  # type: ignore[assignment]
        max_cols = p.max_cols or ctx.book.expected_cols
        li: LineIndex = ctx.product("line_index", page)
        reject: list[str] = []
        flags: list[str] = []
        page_type, policy = "body", "standard"
        if li.n_body == 0:
            reject.append("no_body_column：没有探到正文列（空白页或只有书口小字）")
            page_type, policy = "blank", "skip"
        if max_cols and li.n_body > max_cols:
            flags.append(f"column_overflow：探出 {li.n_body} 列 > 版式上限 {max_cols}（双行小注子列被当成列？）")
        n_wide = sum(1 for ln in li.lines if ln.kind == "wide")
        if n_wide:
            flags.append(f"merged_column：{n_wide} 条宽列（并列/粘连），未进正文")
        n_fn = sum(1 for ln in li.lines if ln.kind == "footnote")
        if n_fn:
            flags.append(f"footnote_column：{n_fn} 条脚注列，未进正文")
        return {"border_detect_gate_manifest": BorderDetectGateManifest(
            page=page, admitted=not reject, reject=reject, flags=flags,
            n_cols=li.n_body, expected_cols=int(max_cols or li.n_body),
            page_type=page_type, page_type_policy=policy)}


attach_gate("line_detect", GateSpec(
    id="line_detect_gate", unit="page", on_fail="block",
    levels=(
        GateLevel(id="L1", unit="page", desc="有没有探到正文列——block，空页不套列窗口", name="no_body_column"),
        GateLevel(id="L1b", unit="page", desc="正文列数是否超过版式上限——flag", name="column_overflow"),
        GateLevel(id="L2", unit="page", desc="有没有并列/粘连的宽列——flag", name="merged_column"),
        GateLevel(id="L3", unit="page", desc="有没有脚注列——flag，只提醒", name="footnote_column"),
    ),
))
