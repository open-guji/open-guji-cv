"""Step2 → Step3 交接闸：只把「确实是一列、且过了闸」的列推给 Step3。

2026-09-09 从 `steps/column_gate.py` 迁到这里（交接闸道，纯重组，判据一个字
没动）：`ColumnGateStep` 本身不变——照旧注册进 `STEPS`、照旧落
`products/<book>/column_gate/`；只是不再出现在 `pipelines/keben_body_v2.yaml`
的 `steps:` 列表里，改用 `core.step.attach_gate` 挂在 `column_warp`（Step2）的
`StepSpec.gate` 上，引擎跑完 Step2 后自动接着跑它（见 `core.engine.Engine.run`）。
落盘目录名特意原样保留，免得触发一次全量重跑（见任务书 §五「本步踩过的坑」）。

判据分三层：
- **L0c 列级**（读 Step1 的 `line_index`，不看几何）：Step1 判定不是正文的列位
  ——筒子页的**版心**（`margin`）、版框外的**页边**（`edge`）——直接拒，拒因说
  「版式如此」。这类列位在几何上完全正常，靠 L1c/L2 拦不住（版心宽度跟正文一样），
  而且**拒因说错会误导人**：报「列宽偏离」会让人去查切列算法，真实原因是这一列
  本来就不是正文。`line_index` 是可选上游，老书的 Step1 产物里没有，缺了就当全是
  正文——行为与加这套东西之前逐位一致。判据与两条负结果见 `utils/column_types.py`；
- **L0 页级**（读闸1，不看几何）：闸1 判 `page_type_policy == "skip"` 的页
  （封面/书签/牌记）直接拒，拒因写页型。这类页 Step2 根本没切列，列数必然
  是 0，再按列数报一句 L1「只探出 0 列」会把人引去查切列算法。page_type 只有
  闸1 一个权威来源，这道闸直接查（与闸3 `row_segment_gate.py` 同一写法）；
- **L1 页级**（只看几何）：探出的列数 = 版式列数。整页性的问题才放这里；
- **L1c 列级**：本列宽偏离本页中位数超 ±15% —— 多半是把界行圈进了列窗。
  ⚠️ 这条**原先错放在页级**，一列坏就整页作废（vol01/42 八列完好只因 c9 坏而全废，
  vol02 全书 27 页被拦、其中 17 页只坏 c1 一列）。2026-09-03 改为列级；
- **L2 列级**：两侧外 25% 最低墨占比 <= 0.045（已知几乎没有独立筛选力，只挡极端）；
- **L2b 列级 —— flag，不是 block**（2026-09-11 新增）：中等面积孤立墨点
  密度 > 0.007（`stamp_noise_density`，见 `column_projection.py` 文档
  字符串）——专挡**整列散布的背景印章噪点**，`side_floor` 只看两侧外沿
  看不见这种污染。命中只写进 `GateColumn.flags`，**不影响 `admitted`**：
  只在 115 列金标上验证过背景印章这一种机制，没见过的书页上会不会有
  没测到的误伤先例还不确定，参照 `row_segment_gate.py` R2/R2s 的先例，
  新判据先以 flag 形式进生产、积累人审证据，不直接硬拦。
  ⚠️ **这条只覆盖四种已知 mixed 机制里的一种**：115 列金标复核，`vol01/146`
  夹注列、`vol02/188` c3/c4 局部弯界行这三条在这个量上跟 clean 完全重叠
  （0.0017~0.0028），不是参数没调对，是这类统计量本身分不开"字身贴边书写"
  和"界行局部探入/夹注贴边"——两者像素层面长得一样，要分需要形状/上下文
  信息，留给人审兜底。别指望调这条判据的阈值能顺带扩大覆盖。
- **L3 金标**：P0 不接（tier=gate）。

页级共享量 period / ref_w 用**几何正常的正文列**算（剔掉 L1c 与 L0c 命中的列）：
L1c 那些列的投影带着一条整界行；L0c 的非正文列（版心只有几个书口小字、页边整片
空白）纵向节律与正文无关。实测剔掉宽度异常列后 period 变化 ≤1.5、ref_w ≤5px。
若正常列不足半数则整页拒绝，因为共识已无意义。
"""

from __future__ import annotations

import statistics

import numpy as np

from pydantic import BaseModel

from ..core.spec import GateLevel, GateSpec, StepSpec, column_key
from ..core.step import RunContext, Step, attach_gate, register_step
from ..products.kinds.border_detect_gate import BorderDetectGateManifest
from ..products.kinds.columns import PageWindows
from ..products.kinds.gate import GateColumn, GateManifest
from ..utils import jiazhu_split
from ..utils.row_boundaries import estimate_shared_period, row_ink_projection


def jiazhu_column_frac(cleaned: np.ndarray, band: tuple[float, float],
                        border_top: float, border_bottom: float,
                        period: float | None, ref_w: float | None,
                        ink_threshold: int = 128) -> float:
    """这一列有多大比例的非空白格像双列小字（`jiazhu_split.column_frac` 的列图版）。

    闸跑在 Step3 之前，拿不到 Step3 的格边界，所以这里按 `period` 均匀分格来
    量——**判据只需要"整列比例"这个粗量，不需要精确的格边界**（实测按均匀
    格分与按 Step3 真边界分，三条夹注列的比例分别是 0.44/0.76/1.00 与
    0.44/0.76/1.00，逐列相同）。`period` 缺失时返回 0（不豁免）。
    """
    if not period or period <= 0:
        return 0.0
    x_lo, x_hi = int(band[0]), int(band[1])
    y0, y1 = max(0.0, border_top), min(float(cleaned.shape[0]), border_bottom)
    if x_hi - x_lo < 8 or y1 - y0 < period:
        return 0.0
    n = max(1, int(round((y1 - y0) / period)))
    patches = {}
    for k in range(n):
        a = int(round(y0 + k * (y1 - y0) / n))
        b = int(round(y0 + (k + 1) * (y1 - y0) / n))
        if b - a >= 8:
            patches[k] = cleaned[a:b, x_lo:x_hi]
    return jiazhu_split.column_frac(patches, ref_w, ink_threshold)


CONTRACT = [
    "页级共享量 period / ref_w 用该页的正文列算（剔掉 L1c 宽度异常与 L0c 非正文列），"
    "不按 admitted 筛——L2/L2b 拒掉的列几何仍是正文，照样参与共识",
    "content_x 随图传：交出去的列图抹白不裁切，Step3 内部找不到墙",
    "border_top / border_bottom 沿用 windows 的 *_in_column；抬头列 top_slack = border_top，"
    "顶格列（版框平齐但顶端有字墨）top_slack = 0.5×period",
    "n_raised 不给：raised 只是几何标记，由 Step3 参数按版式先验定",
]


class ColumnGateParams(BaseModel):
    expected_cols: int | None = None    # None = Book.expected_cols
    count_mode: str = "exact"           # exact：列数必须等于版式列数 | detected：列数由 Step1 探出，只要求 ≥1（现代链）
    width_tol: float = 0.15
    side_floor_max: float = 0.045
    stamp_noise_max: float = 0.007      # L2b：见 column_projection.STAMP_NOISE_MAX 的标定记录
    jiazhu_frac_min: float = jiazhu_split.COLUMN_FRAC_T  # 夹注列豁免门槛，见 L1c/L2 的豁免说明
    tier: str = "gate"                  # gate | gold（gold 需接数据集，P2）
    # 名字像 guardrail 配置，实际不是：这只是一个尚未生效的枚举参数，不落
    # 文件、不是名单，按 doc/data-taxonomy.md 的判断标准仍是普通算法参数
    # （2026-09-11 Step2 数据盘点核实时发现容易误读，记一笔避免下次又查一遍）。
    ink_threshold: int = 128
    bottom_slack: float = 16.0     # 下界在版框线之外再放多少，见 border_bottom 注释
    chars_per_line: int | None = None   # None = Book.chars_per_line；算 n_raised_hint 的基准
    span_ink: float = 0.05         # 量墨跨度时算「有墨」的行墨门槛
    span_margin: float = 0.5       # 跨度/period 超出版式格数多少才判「多一格」
    max_raised_hint: int = 2       # hint 上限，防跨度估歪时暴走


@register_step
class ColumnGateStep(Step):
    spec = StepSpec(
        id="column_gate", title="Step2→3 交接闸", version="1.8", unit="column",
        consumes=("column_windows", "column_image", "border_detect_gate_manifest"),
        optional_consumes=("line_index",),
        produces=("gate_manifest",),
        params=ColumnGateParams,
        code_deps=("open_guji_cv.utils.row_boundaries", "open_guji_cv.utils.column_projection"),
        # `period_prior` 既派生自相关窗口、又是空栏页兜底值；`expected_cols` /
        # `chars_per_line` 是参数为 None 时的取值来源——都影响输出，必须进指纹
        book_deps=("period_prior", "expected_cols", "chars_per_line"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: ColumnGateParams = ctx.params_for(self)  # type: ignore[assignment]
        expected = p.expected_cols or ctx.book.expected_cols
        expected_slots = p.chars_per_line or ctx.book.chars_per_line
        wins: PageWindows = ctx.product("column_windows", page)
        cols = wins.columns
        # **量文字带宽（`band`），不量整列图宽（`warped_size[0]`）**（2026-09-18 修）。
        # 后者含两侧 padding，一列紧贴一条界行时 padding 被撑大、总宽虚高，闸却拿这个
        # 虚高值去判「是不是把界行圈进来了」——band 早就把界行排除在文字带外，闸没用它，
        # 等于拿「排除界行之前」的量去证明「排除界行没排干净」，判据和它自己的说法矛盾。
        # 实锤 bxgb p33c19：warped_size 145px（含左侧界行）判 +20% 拒收，band 127px
        # 只比中位数高 14%——这一列 21 格里被拦到一格都没切出来，是这本书唯一一处
        # Step3 完全空转的列。全书改用 band 后重算：只此一处从「拒」变「收」，
        # 没有新增误报——顺带真拦住了一处此前漏判的（p56c2：band 130px vs 中位 111px，
        # 图上核实是夹注双栏内容被误切成单列，band 判据在这正确起作用）。
        widths = [float(c.band[1] - c.band[0]) for c in cols]
        med_w = statistics.median(widths) if widths else None
        page_reject: list[str] = []

        # 闸1 判 skip 的页（封面/书签/牌记），Step2 根本没切列，列数必然是 0。
        # 这里**不能**再按列数猜一句 L1「只探出 0 列」——page_type 是事实性信息、
        # 只有闸1一个权威来源，拒因说「列数不对」会让人对着 0 列去查切列算法，
        # 真实原因却是这页压根不是正文。与闸3（`row_segment_gate.py`）同一写法：
        # 直接查 `ctx.product`，不经 Step2 转手抄一份。
        # （2026-09-12 那轮「闸2/闸3 都直接读闸1」当时只在闸3 落了地，闸2 这半边
        # 留了个失败的用例 `test_skip_page_then_column_gate_rejects` 挂着，
        # 2026-09-15 补齐。）
        page_type_gate: BorderDetectGateManifest = ctx.product(
            "border_detect_gate_manifest", page)
        if page_type_gate.page_type_policy == "skip":
            page_reject.append(
                f"page_type_skip：闸1判定页型「{page_type_gate.page_type}」，非正文，已跳过切列")
        elif p.count_mode == "detected":
            if not cols:
                page_reject.append("column_count：没有列（Step1 未探到正文列）")
        elif len(cols) != expected:
            page_reject.append(f"column_count：只探出 {len(cols)} 列（版式应为 {expected}）")

        # **列宽偏离是列级判据，不是页级**（2026-09-03 改）。
        # 它逐列算得出，却曾被放在页级拒因里 → 一列坏就整页 9 列作废。
        # 实证：vol01/42 的 c1~c8 偏离都 ≤3.7%、外缘墨 ≤0.008（完好），只有 c9
        # 残留了一条斜界行（宽 +16.6%、外缘墨 0.092），结果 9 列全废。
        # vol02 全书 27 页因它被拦，其中 17 页只坏 c1 一列。
        # 见 doc/step3_error_survey.md 乙类。
        wide_cols = {c.col: (w - med_w) / med_w
                     for c, w in zip(cols, widths)
                     if med_w and abs(w - med_w) > p.width_tol * med_w}

        # L0c：Step1 已判定不是正文的列位（筒子页的版心 `margin`、版框外的页边
        # `edge`）。**拒因要说清是版式如此，不是几何坏了**——版心本来就该在那儿，
        # 报「列宽偏离」会让人去查切列算法。`line_index` 是可选上游：老书的
        # Step1 产物里没有这一种，缺了就当全是正文（行为与加这套东西之前一致）。
        non_body: dict[int, tuple[str, str]] = {}
        try:
            li = ctx.product("line_index", page)
        except Exception:
            li = None
        if li is not None:
            for ln in li.lines:
                if ln.col is not None and ln.kind != "body":
                    non_body[ln.col] = (ln.kind, (ln.flags or [""])[0])

        # 逐列：页级先验要用**几何正常的正文列**算。
        # 宽度异常的列多半是把界行圈进了列窗，它的投影带着一条整线；
        # 非正文列（版心只有几个书口小字、页边整片空白）更不该参与——
        # 它们的纵向节律与正文无关，会把 period / ref_w 带偏。
        # 实测剔掉宽度异常列后 period 变化 ≤1.5、ref_w ≤5px。
        projs, borders, dst_ws, band_ws = [], [], [], []
        for c in cols:
            if c.col in wide_cols or c.col in non_body:
                continue
            cleaned = ctx.image("column_image", column_key(page, c.col))
            b0, b1 = c.band
            projs.append(row_ink_projection(cleaned, b0, b1, ink_threshold=p.ink_threshold))
            borders.append((c.border_top_in_column, c.border_bottom_in_column))
            dst_ws.append(b1 - b0)
            band_ws.append(float(b1 - b0))

        period = ref_w = None
        page_flags: list[str] = []
        period_from_prior = False
        if not page_reject:
            need = max(1, len(cols) // 2) if p.count_mode == "detected" else max(2, expected // 2)
            if len(projs) < need:
                page_reject.append(
                    f"period_fallback：几何正常的列只剩 {len(projs)} 条，不足以定页级先验")
            else:
                try:
                    period = round(float(estimate_shared_period(
                        projs, borders, dst_ws, period_prior=ctx.book.period_prior)), 2)
                except ValueError as e:
                    # 空栏页兜底（2026-09-13）：栏内没有字就推不出纵向节律，
                    # 这不是故障——界行齐全、九列切得出来，该正常产出一个
                    # 「各格皆空」的页。用书级 period 先验顶上。
                    #
                    # 为什么书级常量靠得住：正文页的 period 是版式常量，实测
                    # vol01 正文 108 页 115.0±1.67px、vol02 186 页 113.0±2.37px
                    # （与 `bottom_gap` 那条跨页一致性先验同一个套路）。
                    #
                    # **只在估不出来时兜底**——能估出来的页一律用当场估的值，
                    # 所以配了这个数也不会改变任何正常页的产物。
                    if ctx.book.period_prior:
                        period = float(ctx.book.period_prior)
                        period_from_prior = True
                        page_flags.append(
                            f"period_fallback：页级周期估不出来（{e}），已用书级先验 "
                            f"{period:g}px 兜底——多半是空栏页（栏内无字，无纵向节律）")
                    else:
                        page_reject.append(
                            f"period_fallback：页级周期估不出来（{e}）"
                            f"；本册未配 period_prior，空栏页无法兜底")
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
        # 同一次列图读取里顺带算 `n_raised_hint`：**这一列的墨跨度装得下几个字**。
        # 「抬头多一个字」是逐列的（vol01/33 四个抬头列实测 3 个多一字、1 个不多），
        # 而 `n_raised` 只有页级参数一个来源 —— 给不出逐列值时 DP 只能在 21 格里
        # 硬塞 22 个字，唯一可行解是**丢掉首字**。实测 8 列（26c6、33c7/c8、
        # 47c6/c9、vol02/3c3~c5）跨度/period 达 21.4~22.2，首字整个落在首格之上。
        # 判据用**墨跨度**而不是「顶端有没有墨」——后者分不开「顶格写」与「多一个字」。
        top_ink_slack: dict[int, float] = {}
        n_raised_hint: dict[int, int] = {}
        # `expected_slots is None` = 现代链（册配置 `chars_per_line: null`，格数由块宽 ÷ pitch 推）。
        # 这一整块量的是「抬头列比版式常量多几格」，**是刻本的概念**：现代印刷没有版框、
        # 没有抬头框，也没有「版式应有 21 格」这个基准，跨度 hint 无从算起。
        # 2026-09-15：不跳过就会在 `span / period - expected_slots` 上 float - None 崩掉
        # （考補萃編横排书第一次跑 Step2 撞到）。
        if page_ok and period and expected_slots is not None:
            probe = max(20, int(round(period * 0.6)))
            for c in cols:
                try:
                    img = ctx.image("column_image", column_key(page, c.col))
                except Exception:
                    continue
                b0, b1 = c.band
                prof = (img[:, int(b0):int(b1)] < p.ink_threshold).mean(axis=1)

                # ⚠️ **hint 是「探测失败时的兜底」，跟抬头框互斥，不能叠加**
                # （2026-09-12 修）。原设计本来就是二选一：
                #   探到抬头框 → 窗口抬到框上（`border_top_in_column > 0`），
                #                 多出来的格由 DP 按窗口高度自己切出来；
                #   没探到     → 窗口裁在版框线上，靠墨跨度 hint 补格数。
                # 两条路各算一次「多几格」，同时生效就会**把同一格数加两遍**。
                #
                # 此前一直不暴露，是因为 vol02/vol03 的抬头框一个都没探到
                # （`HR_DIST_MIN`/`HR_WALL_MIN_FRAC` 卡在边界，同日已修），
                # 只有兜底那条在跑。抬头框一恢复探测，21 列立刻双算：
                # vol02/11 c4「御定易經通注」、101 c6「聖祖仁皇帝」人裁 n_raised=1，
                # 算法给 2——`slot -2` 才是真在框上的字，`slot -1`（定/祖）是被
                # 推进负号区的普通正文字。vol01 那 18 列是**历史遗留的同一个 bug**
                # （vol01 探测一直是好的，只是没人对过账）。
                #
                # 跨度这个量本身也只在「裁在版框线上」时才准：实测同一列
                # 旧裁法 21.40~21.56（hint 0~1，对），抬到框上 22.52~22.65
                # （hint 2，错）——它量的是「窗口里装得下几个字」，窗口一变
                # 基准就没了。所以这里按窗口来源分流，而不是去调 `span_margin`。
                if c.border_top_in_column > 1.0:
                    # 探到抬头框：格数**由窗口高度定**，不再量墨跨度。
                    # 窗口上界已经抬到抬头框内沿之上（`page_column_windows` 减了
                    # `HEAD_PAD=30`），所以框上高度 / period 就是「框上装得下几格」。
                    # 实测零重叠：抬头列 1.02~1.55（vol02 三条、vol01 十二条），
                    # 普通列恒 0.00 —— `int()` 取整即可，不需要再标定阈值。
                    n_raised_hint[c.col] = min(
                        max(1, int(c.border_top_in_column / period)),
                        p.max_raised_hint)
                else:
                    ink = np.flatnonzero(prof > p.span_ink)
                    if ink.size:
                        span = float(ink[-1] - ink[0])
                        extra = int(span / period - expected_slots + p.span_margin)
                        if extra > 0:
                            n_raised_hint[c.col] = min(extra, p.max_raised_hint)

                if c.raised or c.border_top_in_column > 1.0:
                    continue                      # 真抬头列的 top_slack 走原路
                head = prof[:probe]
                if head.size and float(head.max()) > 0.08:
                    top_ink_slack[c.col] = round(float(period) * 0.5, 2)

        # 夹注列比例：**只对「本来要被 L1c/L2 拒掉」的列算**（每列要逐格跑
        # 一遍缝判据，不便全列算；正常列算了也用不上——豁免只在有拒因时才有
        # 意义）。非正文列（版心/页边）不算：L0c 不在豁免范围内。
        jz_fracs: dict[int, float] = {}
        for c in cols:
            if c.col in non_body:
                continue
            if c.col not in wide_cols and c.side_floor <= p.side_floor_max:
                continue
            try:
                cleaned = ctx.image("column_image", column_key(page, c.col))
            except Exception:
                continue
            jz_fracs[c.col] = round(jiazhu_column_frac(
                cleaned, c.band, c.border_top_in_column, c.border_bottom_in_column,
                period, ref_w, p.ink_threshold), 3)

        recs: list[GateColumn] = []
        for c in cols:
            reasons: list[str] = []
            flags: list[str] = []
            if c.col in non_body:
                kind, why = non_body[c.col]
                label = {"margin": "版心（书口）", "edge": "版框外页边"}.get(kind, kind)
                reasons.append(f"non_body_column：Step1 判定本列位是{label}，非正文"
                               + (f"——{why}" if why else ""))
            if not page_ok:
                reasons.append("页级未过 L1")
            # **夹注列豁免**（2026-09-17）：L1c 与 L2 都建立在「正文列 = 一列
            # 居中的大字」这个前提上——L1c 认为超宽是圈进了界行，L2 认为两侧
            # 外沿有墨是列窗没对齐。**大段双行小注把这两个前提同时打破**：
            # 两个小字并排合起来本来就顶满列宽（两侧外沿当然有墨），排得密的
            # 列文字带也确实比正文列宽。
            # 实锤：bxgb p56c1/c2、p8c13 三列被这两条拒掉，Step3 根本没跑；
            # 绕过闸直接切，夹注 a/b 全部切对（p56c2 读序出来正是
            # 「二里此云過永康數里飯至李」），是闸在丢好数据，不是切分不行。
            # 判据用 `jiazhu_column_frac`——全书 931 列实测普通列 p99 0.048、
            # 这三列 0.44/0.76/1.00，两个分布中间空一大档（标定见
            # `jiazhu_split.COLUMN_FRAC_T`）。
            # ⚠️ 只豁免这两条**几何前提被版式打破**的闸；L0c（版心/页边，版式
            # 事实）与 L2b（噪点 flag）不在豁免范围内——版心就算印得像夹注也
            # 不是正文。
            jz_frac = jz_fracs.get(c.col, 0.0)
            is_jiazhu_col = jz_frac >= p.jiazhu_frac_min
            if is_jiazhu_col:
                flags.append(f"column_width/side_ink 豁免：本列 {jz_frac:.0%} 的非空白格呈双列小字，"
                             "判为夹注列（两侧顶满列宽是版式如此，不是列窗没对）")
            if c.col in wide_cols and not is_jiazhu_col:
                band_w = c.band[1] - c.band[0]
                reasons.append(f"column_width：本列文字带宽 {band_w}px 偏离本页中位数 "
                               f"{med_w:.0f}px {wide_cols[c.col]:+.0%}（多半圈进了界行/夹注双栏）")
            if c.side_floor > p.side_floor_max and not is_jiazhu_col:
                reasons.append(f"side_ink：两侧最低墨占比 {c.side_floor:.4f} > {p.side_floor_max}")
            if c.stamp_noise > p.stamp_noise_max:
                # flag 级，不进 reject：只在 115 列金标上验证过背景印章这一种机制，
                # 未见过的书页上有没有误伤先例不确定，先标记攒人审证据，不硬拦。
                flags.append(f"stamp_noise：整列噪点密度 {c.stamp_noise:.4f} > {p.stamp_noise_max}"
                             "（疑似背景印章污染，flag 不算错）")
            if p.tier == "gold":
                reasons.append("human_verdict：金标准入尚未接入（P2）")
            recs.append(GateColumn(
                col=c.col, admitted=not reasons, reject=reasons, flags=flags, tier=p.tier,
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
                n_raised_hint=n_raised_hint.get(c.col, 0),
                raised=c.raised, head_raise_inner_y=c.head_raise_inner_y,
                warped_size=c.warped_size, side_floor=c.side_floor,
                stamp_noise=c.stamp_noise,
                band_width=float(c.band[1] - c.band[0]),
            ))
        return {"gate_manifest": GateManifest(
            page=page, admitted=page_ok, reject=page_reject, flags=page_flags,
            period=period, ref_w=ref_w, period_from_prior=period_from_prior,
            column_widths=widths, median_width=med_w, columns=recs, contract=CONTRACT)}


# 挂到 Step2（column_warp）出口——levels 的 desc 只描述层次，不重复具体阈值数字
# （阈值在 ColumnGateParams 里，写两处会漂）。
COLUMN_GATE_SPEC = GateSpec(
    id="column_gate", unit="column", on_fail="block",
    levels=(
        GateLevel(id="L0c", unit="column",
                  desc="Step1 判定本列位不是正文（筒子页版心 / 版框外页边）——"
                       "版式如此，不是几何坏了", name="non_body_column"),
        GateLevel(id="L1", unit="page",
                  desc="探出的列数是否等于版式列数——整页性的问题才放这一层", name="column_count"),
        GateLevel(id="L1f", unit="page",
                  desc="页级周期估不出来时是否用书级 period_prior 兜底——flag，"
                       "不拦（空栏页栏内无字、推不出纵向节律，不是故障）", name="period_fallback"),
        GateLevel(id="L1c", unit="column",
                  desc="本列宽是否偏离本页中位数过多——多半是把界行圈进了列窗", name="column_width"),
        GateLevel(id="L2", unit="column",
                  desc="两侧外沿最低墨占比是否超界——已知几乎没有独立筛选力，只挡极端", name="side_ink"),
        GateLevel(id="L2b", unit="column",
                  desc="整列中等面积孤立墨点密度是否超界——flag 不是 block，"
                       "专挡背景印章噪点，只覆盖四种已知污染机制里的一种", name="stamp_noise"),
        GateLevel(id="L3", unit="column",
                  desc="人裁金标准入（P2 未接，tier=gate 时不生效）", name="human_verdict"),
    ),
)
attach_gate("column_warp", COLUMN_GATE_SPEC)
# 现代印刷链的 Step2（column_crop）出口挂同一道闸：产物种类相同，判据里列数比对由
# `count_mode=detected`（modern_body.yaml 的 params）放开。
attach_gate("column_crop", COLUMN_GATE_SPEC)
