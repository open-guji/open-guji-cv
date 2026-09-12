"""Step1 → Step2 交接闸：把「页型是正文类、且探对了列数」的页推给 Step2；
界行弯度/版框墨/抬头框只标记不拦（现在都还没有已验证的"超了就该整页
作废"的判准）。

判据来自 overview `项目进展/图片初步数字化/进度/交接闸/README.md` 那张
八道闸判据表（"闸1 边框 | 页/列 | 列数、界行 w80、版框墨、抬头框距离"），
但表上说的"判据已存在"没有逐条验证过——核实后结论分两半：

- **列数比对是文档失实**：现行 P0 流水线（`steps/border_detect.py` →
  `core/engine.py`）里根本没有拿探出的 `verticals` 数量跟 `expected_cols`
  比较的代码；唯一有这段逻辑的是一套已经跟当前流水线脱钩的旧模块
  （`open_guji_cv/detectors/borders.py`，走独立的旧 `pipeline.py`，
  4 月后再没改过），不能当"已有判据"复用，这里是从零写的。
- **界行 w80 / 版框墨 / 抬头框距离，计算逻辑确实都在**，只是嵌在探测
  算法内部当筛选/分支用，不是独立的质检判据：
  - `bend_w80_med/max` 是直线拟合下的 w80，`BEND_W80_MED/MAX`
    （`utils/border_geometry.py`）本来是"要不要转三段折线"的决策阈值，
    但单条线的 w80 本身就是"这条线拟合得好不好"的信号——按模块注释里
    vol01/11 那个案例（页级中位 9.5、单条线跑到 64，只看中位会漏），
    复用同一个 `BEND_W80_MAX` 判"单条线是否跑飞"是同一个量、不是另造。
  - 版框墨：`detect_outer_borders()` 探不到就返回 `None`（docstring
    明确写"没印上的页标 None 不报数"），这里直接读现成的
    `top_outer_offset`/`bottom_outer_offset` 是否为 None，不重新算墨占比。
  - 抬头框距离 `HR_DIST_MIN/MAX=90/210`：探测阶段（`detect_head_raise`）
    已经用它筛过候选，`head_raise` 里留下来的天然都在区间内——闸1不需要
    重复判这条，只报"这一页有几个抬头"供人复核数量是否合理（比如
    忽然从 0 跳到很多，可能是别的页面特征误判成台阶）。
"""

from __future__ import annotations

from pydantic import BaseModel

from ..clustering.page_type import classify_page_type
from ..core.spec import GateLevel, GateSpec, StepSpec
from ..core.step import RunContext, Step, attach_gate, register_step
from ..products.kinds.border_detect_gate import BorderDetectGateManifest
from ..products.kinds.borders import Borders
from ..utils.border_geometry import BEND_W80_MAX


class BorderDetectGateParams(BaseModel):
    expected_cols: int | None = None    # None = Book.expected_cols
    bend_w80_max_gate: float = BEND_W80_MAX   # 复用探测阶段判"单条线跑飞"的同一个量


@register_step
class BorderDetectGateStep(Step):
    spec = StepSpec(
        id="border_detect_gate", title="Step1→2 交接闸", version="1.0", unit="page",
        consumes=("borders",), produces=("border_detect_gate_manifest",),
        params=BorderDetectGateParams,
        code_deps=("open_guji_cv.utils.border_geometry", "open_guji_cv.clustering.page_type"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: BorderDetectGateParams = ctx.params_for(self)  # type: ignore[assignment]
        expected = p.expected_cols or ctx.book.expected_cols
        if not ctx.has_product("borders", page):
            # borders 缺失时不读原图判页型——上游缺产物往往就是因为原图本身
            # 缺失（`raw_page` 会抛 FileNotFoundError），这条分支要的是宽容
            # 报错，不该在这里引入新的失败点。
            return {"border_detect_gate_manifest": BorderDetectGateManifest(
                page=page, admitted=False, reject=["L1：上游 borders 产物缺失"],
                n_cols=0, expected_cols=expected)}
        page_type, policy = classify_page_type(ctx.raw_page(page))
        b: Borders = ctx.product("borders", page)
        n_cols = max(0, len(b.verticals) - 1)   # verticals 是 N+1 条外边框线

        reject: list[str] = []
        if policy == "skip":
            reject.append(f"L0：页型判定为「{page_type}」，无正文栏格，不套列窗口")
        if n_cols != expected:
            reject.append(f"L1：探出 {n_cols} 列（版式应为 {expected}）")

        flags: list[str] = []
        if policy == "custom":
            flags.append(f"L0c：页型判定为「{page_type}」，列数预期与正文不同，未核验")
        if policy is None:
            flags.append("L0c：页型判不准（uncertain），按 body/standard 兜底处理")
        if b.bend_w80_max is not None and b.bend_w80_max >= p.bend_w80_max_gate:
            flags.append(f"L2：单条界行 w80 达 {b.bend_w80_max:.1f}px "
                        f"（>= {p.bend_w80_max_gate}），这条线可能跑飞了")
        if b.top_outer_offset is None:
            flags.append("L3：上外框没探到（可能没印上，也可能该有却漏了，未区分）")
        if b.bottom_outer_offset is None:
            flags.append("L3：下外框没探到（可能没印上，也可能该有却漏了，未区分）")

        return {"border_detect_gate_manifest": BorderDetectGateManifest(
            page=page, admitted=not reject, reject=reject, flags=flags,
            n_cols=n_cols, expected_cols=expected,
            bend_w80_max=b.bend_w80_max,
            top_outer_offset=b.top_outer_offset, bottom_outer_offset=b.bottom_outer_offset,
            n_head_raise=len(b.head_raise),
            page_type=page_type, page_type_policy=policy or "standard")}


# 挂到 Step1（border_detect）出口——levels 的 desc 只描述层次，不重复具体阈值数字
# （阈值在 BorderDetectGateParams / border_geometry 常量里，写两处会漂）。
attach_gate("border_detect", GateSpec(
    id="border_detect_gate", unit="page", on_fail="block",
    levels=(
        GateLevel(id="L0", unit="page",
                  desc="页型是否判定为 skip 类（封面/书签/空白/牌记）——block 级，"
                       "这些页没有正文栏格，套列窗口是无中生有"),
        GateLevel(id="L0c", unit="page",
                  desc="页型是否为 custom（如上諭，列数与正文不同）或判不准——"
                       "flag，不拦（custom 还没有专门的窄列处理逻辑，"
                       "uncertain 按 body/standard 兜底）"),
        GateLevel(id="L1", unit="page",
                  desc="探出的列数是否等于版式列数——block 级判据，"
                       "列窗口错了 Step2 整页都没法射影"),
        GateLevel(id="L2", unit="page",
                  desc="是否有单条界行 w80 跑飞——flag，不拦（未验证阈值超了必错）"),
        GateLevel(id="L3", unit="page",
                  desc="上/下外框有没有探到——flag，不拦（没印上是正常情况，"
                       "现在分不清「没印上」与「该有却漏探」）"),
    ),
))
