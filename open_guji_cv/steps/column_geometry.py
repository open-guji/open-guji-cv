"""2 切字·列几何：每列的文字带、格线范围、页级纵向字距，以及「这一列能不能切」。

五小步之后、字间切分之前的一步（2026-11-25 用户定：出口闸只在最后调用；这里**只算量，不判质量**）。
原 `gates/column_gate.py` 的 Step 把两种东西混在一个产物 `gate_manifest` 里：
- 计算量：页级 `period`（纵向字距，含书级 `period_prior` 兜底）、`ref_w`、`median_width`、`column_widths`；
  列级 `content_x`、`border_top/bottom`、`top_slack`、`n_raised_hint`、`raised`、`band_width`。字间切分读的正是这些；
- 裁决：`reject`、`flags`、`admitted`，用来挡掉不合格的列。
计算量搬到这里，算法一字未改；**结构性不切**（页型 skip、`line_index` 判非正文列位、册配置点名的表格列、
页级周期估不出来）仍记在 `admitted`／`reject` 里，因为这是版式事实，不是质量问题；
质量判据（列数、列宽、界行残墨、印章噪点、框线残留、夹注豁免……）全部归最后的出口闸 `cut_gate`。

产物 `column_geometry` 用 `GateManifest` 的形状（字段与拆分前的 `gate_manifest` 一致），`flags` 为空。
"""

from __future__ import annotations

import statistics

import numpy as np
from pydantic import BaseModel, model_serializer

from ..core.book import _expand_pages
from ..core.spec import StepSpec, column_key
from ..core.step import RunContext, Step, register_step
from ..impl.keben.column_pair_merge import has_pair_merged
from ..impl.keben.row_boundaries import estimate_shared_period, row_ink_projection
from ..products.kinds.border_detect_gate import BorderDetectGateManifest
from ..products.kinds.columns import PageWindows
from ..products.kinds.gate import GateColumn, GateManifest
from ._colview import merged_windows

TABLE_COLUMN_REJECT = "table_column"

def trim_dash_ends(mask: np.ndarray, period: float, run_max_frac: float,
                   gap_min_frac: float, merge_frac: float) -> tuple[int, int] | None:
    """行有墨掩码的首尾各剥掉「孤立的虚线残段」，返回剩下的 (首行, 末行)；全无墨 → None。

    列图两端偶尔留着版框内侧那条**虚线**的残段：几行厚的细墨、常成簇（相隔十几行的
    两三小段），跟正文之间隔着一两格以上的空白。`n_raised_hint` 量的是「首末墨行之间
    装得下几格」，这簇薄墨把跨度撑大 2 格左右，凭空多出一格抬头（vol03 p28c2：残段在
    第 19~23 行，首字要到 272 行才起，跨度/period 21.68 → hint=1；剥掉后 19.4）。

    做法：相隔 < `merge_frac×period` 的墨段并成一簇；从端部起，簇的纵向跨度
    ≤ `run_max_frac×period` **且**到下一簇的空隙 ≥ `gap_min_frac×period` 的簇整簇剥掉，
    直到碰上第一簇「不像虚线」的墨为止；只剩一簇时不再剥。
    判据靠**尺寸与孤立度**、不靠墨浓度——实测 vol03 90 个兜底 hint 列：虚线簇跨度
    ≤29 行、后接空隙 ≥185 行（1.7 格）；真首字簇跨度 ≥147 行或紧贴下一字（空隙 ≤41），
    两头都有大余量，而残段的峰值墨占比 0.05~0.84 都有（混着满宽版框条残渣），分不开。
    """
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return None
    breaks = np.flatnonzero(np.diff(idx) > 1)
    starts = np.concatenate(([idx[0]], idx[breaks + 1]))
    ends = np.concatenate((idx[breaks], [idx[-1]]))
    merge = merge_frac * period
    cs, ce = [int(starts[0])], [int(ends[0])]
    for a, b in zip(starts[1:], ends[1:]):
        if a - ce[-1] - 1 < merge:
            ce[-1] = int(b)
        else:
            cs.append(int(a))
            ce.append(int(b))
    thin_max = run_max_frac * period
    gap_min = gap_min_frac * period
    lo, hi = 0, len(cs) - 1
    while lo < hi and (ce[lo] - cs[lo] + 1) <= thin_max and (cs[lo + 1] - ce[lo] - 1) >= gap_min:
        lo += 1
    while hi > lo and (ce[hi] - cs[hi] + 1) <= thin_max and (cs[hi] - ce[hi - 1] - 1) >= gap_min:
        hi -= 1
    return cs[lo], ce[hi]



CONTRACT = [
    "页级共享量 period / ref_w 用该页的正文列算（剔掉 L1c 宽度异常与 L0c 非正文列），"
    "不按 admitted 筛——L2/L2b 拒掉的列几何仍是正文，照样参与共识",
    "content_x 随图传：交出去的列图抹白不裁切，Step3 内部找不到墙",
    "border_top / border_bottom 沿用 windows 的 *_in_column；抬头列 top_slack = border_top，"
    "顶格列（版框平齐但顶端有字墨）top_slack = 0.5×period",
    "n_raised 不给：raised 只是几何标记，由 Step3 参数按版式先验定",
]




class ColumnGeometryParams(BaseModel):
    expected_cols: int | None = None    # None = Book.expected_cols
    expected_cols_pages: dict[int, int] = {}
    """按页列数（2026-11-12，殿本 vol01 p100：图上 10 列、版框只探出 9 列，参校本质检）：`{页: 本页列数}`，覆盖册级 `expected_cols`。
    职名页、个别页列数与册级不同时用；一般同 `vline_overrides` 配用（给出本页全部竖线）。border_detect、border_detect_gate、
    column_gate 三处都要写同一张表。缺省空，空时不进参数 dump，产物与加字段前逐字节相同。"""
    count_mode: str = "exact"           # exact：列数必须等于版式列数 | detected：列数由 Step1 探出，只要求 ≥1（现代链）
    width_tol: float = 0.15
    ink_threshold: int = 128
    bottom_slack: float = 16.0     # 下界在版框线之外再放多少，见 border_bottom 注释
    chars_per_line: int | None = None   # None = Book.chars_per_line；算 n_raised_hint 的基准
    span_ink: float = 0.05         # 量墨跨度时算「有墨」的行墨门槛
    top_flush_min_frac: float = 0.25   # 顶格判定：顶端一格内 >8% 墨的行数 ≥ 此比例×period 才算字（毛边只有几行）
    span_margin: float = 0.5       # 跨度/period 超出版式格数多少才判「多一格」
    max_raised_hint: int = 2       # hint 上限，防跨度估歪时暴走
    #: 兜底 hint 量跨度前先剥掉两端孤立的薄虚线段（见 `trim_dash_ends`）。**默认关**，
    #: 关着时产物逐字节不变。（2026-10-02 S2 道：vol03 p28c2/p39c9 一类假抬头）
    hint_ignore_dash: bool = False
    hint_dash_run_max_frac: float = 0.3    # 虚线簇纵向跨度上限 ×period（实测 ≤29 行 ≈ 0.26；真字簇 ≥147 行）
    hint_dash_gap_min_frac: float = 1.2    # 簇与下一簇墨的最小空隙 ×period（实测 ≥185 行 ≈ 1.67；真字 ≤41）
    hint_dash_merge_frac: float = 0.25     # 相隔小于此 ×period 的墨段并成一簇
    #: `frame_residue`：端部残留满宽段达到多少行判「版框没削干净」。
    #: 3 是实测定的——正常削干净的 d/e 两档 1065 个端口最长段**全是 0**，
    #: 而 b 档（框字粘连）最小 6，两侧都有余量。标定见
    #: `steps/column_warp.FRAME_RESIDUE_*`（含被证伪的「端部峰值」候选）。
    period_prior_pages: list[int | str] = []
    #: **页级周期偏离书级先验太多时回落先验**（2026-10-21，殿本 vol04 p127 c3 整列格线错半格）。
    #: 正文页的格高是版式常量：殿本 vol04/05/09 正文页的估值都在先验 ±5% 以内。偏出 ±这么多的页，
    #: 估值是被卷末大印、整页空白带偏的（vol04 p127/128/220 估 89–95、vol05 p188 102、vol09 p162 99.5，
    #: 先验 115），Step3 拿它当格高，抬头格数、格网全乱。0 = 关（只剩上面贴下界那一条）。没配
    #: `period_prior` 的书不受影响。
    period_prior_tol: float = 0.10
    #: **半文半表页按列标表**（GUJI-772，2026-11-16，史記年表卷首／卷末页一半表一半正文）：`{页: [列号…]}`，列号同
    #: 产物 col（图上右起第几列，从 1 起；产物 quad／box 是右上原点，x 小的列在图右边），写法同页号（`["1-5"]`、`[6, 7]`）。点名的列按版式事实拒收（拒因前缀
    #: `table_column`，同 L0c 版心一路：不参与页级周期与列宽中位，Step3 出 ok=False 不切，对位、定字跳过），
    #: 页型仍是正文，其余列照常切。页级周期门槛扣掉表格列数、下限 1 列（正文只剩一列也照估；估不出来走书级 `period_prior` 兜底，要可靠就点名 `period_prior_pages`）。
    #: 产物口径：`column_widths` 仍记全部列，`median_width` 只按正文列算。册配置里写 `page_kinds: {table_cols: …}`
    #: （`core/page_kinds.py` 翻成本参数）。缺省空，空时不进参数 dump，产物与加字段前逐字节相同。
    table_cols: dict[int, list[int | str]] = {}


    @model_serializer(mode="wrap")
    def _drop_off_period_override(self, handler):
        # 两个开关关着时剔出 dump：params_hash 与加开关前逐位相同（同 border_detect_gate 写法）
        d = handler(self)
        if isinstance(d, dict):
            if not self.period_prior_pages:
                d.pop("period_prior_pages", None)
            if not self.expected_cols_pages:
                d.pop("expected_cols_pages", None)
            if not self.table_cols:
                d.pop("table_cols", None)
        return d




@register_step
class ColumnGeometryStep(Step):
    spec = StepSpec(
        id="column_geometry", title="2 列几何（文字带、格线范围、页级字距）", version="1.0", unit="column",
        consumes=("column_windows", "column_bands", "column_ends", "column_image", "border_detect_gate_manifest"),
        optional_consumes=("line_index",),
        produces=("column_geometry",),
        params=ColumnGeometryParams,
        code_deps=("open_guji_cv.impl.keben.row_boundaries", "open_guji_cv.seg.warp", "open_guji_cv.seg.profile",
                   "open_guji_cv.impl.keben.column", "open_guji_cv.impl.keben.column_pair_merge"),
        # `period_prior` 既派生自相关窗口、又是空栏页兜底值；`expected_cols` / `chars_per_line` 是参数为 None 时的取值来源
        book_deps=("period_prior", "expected_cols", "chars_per_line"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: ColumnGeometryParams = ctx.params_for(self)  # type: ignore[assignment]
        expected = p.expected_cols_pages.get(page) or p.expected_cols or ctx.book.expected_cols
        expected_slots = p.chars_per_line or ctx.book.chars_per_line
        wins: PageWindows = merged_windows(ctx, page)
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
        # 半文半表页：点名的表格列不算列宽中位（表格列宽与正文列无关）；没点名的页逐位照旧
        tc_spec = p.table_cols.get(page) if p.table_cols else None
        table_cols = set(_expand_pages(list(tc_spec))) if tc_spec else set()
        if table_cols:
            tw = [w for c, w in zip(cols, widths) if c.col not in table_cols]
            med_w = statistics.median(tw) if tw else med_w
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
        # 窄对合并页（见 `border_detect_gate`）：闸1 认了合并旗、且记的期望列数＝本闸期望−1，才按它判列数；
        # 对不上（闸1 留的是 `pair_merged_inconsistent`、或两闸期望不同）就不放宽。
        if has_pair_merged(page_type_gate.flags) and page_type_gate.expected_cols == expected - 1:
            expected = page_type_gate.expected_cols
        if page_type_gate.page_type_policy == "skip":
            page_reject.append(
                f"page_type_skip：闸1判定页型「{page_type_gate.page_type}」，非正文，已跳过切列")
        elif not cols:
            page_reject.append("column_count：没有列（Step1 未探到正文列）")

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
        # 半文半表页（`table_cols`）：册配置点名的表格列，同版心一样是版式事实，不进页级先验、整列拒收
        for c in cols:
            if c.col in table_cols and c.col not in non_body:
                non_body[c.col] = ("table", "")

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
            if table_cols:     # 半文半表页：门槛扣掉表格列数 k，下限 1（正文只剩一列也照估，估不出用 period_prior 兜底）
                k = len(table_cols & {c.col for c in cols})
                need = max(1, ((len(cols) if p.count_mode == "detected" else expected) - k) // 2)
            if len(projs) < need:
                page_reject.append(
                    f"period_fallback：几何正常的列只剩 {len(projs)} 条，不足以定页级先验")
            elif (p.period_prior_pages and ctx.book.period_prior
                  and page in set(_expand_pages(p.period_prior_pages))):
                period = float(ctx.book.period_prior)
                period_from_prior = True
                page_flags.append(
                    f"period_fallback：本页在册配置 period_prior_pages 里点名，"
                    f"不估页级周期，直接用书级先验 {period:g}px")
                ref_w = float(statistics.median(band_ws)) if band_ws else None
            else:
                try:
                    period = period_est = round(float(estimate_shared_period(
                        projs, borders, dst_ws, period_prior=ctx.book.period_prior)), 2)
                    prior = ctx.book.period_prior
                    if p.period_prior_tol and prior and abs(period / prior - 1) > p.period_prior_tol:
                        period = float(prior)
                        period_from_prior = True
                        page_flags.append(
                            f"period_fallback：页级周期估值 {period_est:g}px 偏离书级先验超过 "
                            f"{p.period_prior_tol:.0%}，已用先验 {period:g}px")
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
                            f"；本册未配 period_prior，空栏页无法兜底。"
                            f"先标一下：`guji calibrate {ctx.book.id} --pages all --with-bottom-gap`，"
                            f"把测出来的 period_prior 写进 books/{ctx.book.id}.yaml")
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
                if c.col in table_cols:       # 半文半表页的表格列：不量抬头／顶格
                    continue
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
                    if p.hint_ignore_dash and ink.size:
                        ends = trim_dash_ends(prof > p.span_ink, period,
                                              p.hint_dash_run_max_frac,
                                              p.hint_dash_gap_min_frac,
                                              p.hint_dash_merge_frac)
                        if ends is not None:
                            ink = np.array(ends)
                    if ink.size:
                        span = float(ink[-1] - ink[0])
                        extra = int(span / period - expected_slots + p.span_margin)
                        if extra > 0:
                            n_raised_hint[c.col] = min(extra, p.max_raised_hint)

                if c.raised or c.border_top_in_column > 1.0:
                    continue                      # 真抬头列的 top_slack 走原路
                head = prof[:probe]
                # 顶格的判据要「像个字」：>8% 的行数 ≥ top_flush_min_frac×period。原来只看
                # 「有没有一行 >8%」，版框条下沿的毛边（9 行、宽 19~36%）也算顶格
                # （2026-09-20 vol01/141 c1/c3：Step2 把上界提到框内缘后毛边露出来，
                # c1/c3 各拿到 58px slack，Step3 在首格切出一个假 char）。真顶格字
                # 117 行（c7「諭旨」），0.25×period ≈ 28 行分得开。
                if head.size and int((head > 0.08).sum()) >= max(12, int(period * p.top_flush_min_frac)):
                    top_ink_slack[c.col] = round(float(period) * 0.5, 2)

        # 夹注列比例：**只对「本来要被 L1c/L2 拒掉」的列算**（每列要逐格跑
        # 一遍缝判据，不便全列算；正常列算了也用不上——豁免只在有拒因时才有
        # 意义）。非正文列（版心/页边）不算：L0c 不在豁免范围内。
        recs: list[GateColumn] = []
        for c in cols:
            reasons: list[str] = []
            if c.col in non_body and non_body[c.col][0] == "table":
                reasons.append(f"{TABLE_COLUMN_REJECT}：册配置 page_kinds.table_cols 点名本列为表格列，不切")
            elif c.col in non_body:
                kind, why = non_body[c.col]
                label = {"margin": "版心（书口）", "edge": "版框外页边"}.get(kind, kind)
                reasons.append(f"non_body_column：Step1 判定本列位是{label}，非正文"
                               + (f"——{why}" if why else ""))
            if not page_ok:
                reasons.append("页级未过 L1")
            recs.append(GateColumn(
                col=c.col, admitted=not reasons, reject=reasons, flags=[], tier="gate",
                content_x=(float(c.band[0]), float(c.band[1])),
                border_top=float(c.border_top_in_column),
                border_bottom=float(min(c.warped_size[1],
                                        c.border_bottom_in_column + p.bottom_slack)),
                top_slack=(float(c.border_top_in_column) if c.raised
                           else top_ink_slack.get(c.col, 0.0)),
                n_raised_hint=n_raised_hint.get(c.col, 0),
                raised=c.raised, head_raise_inner_y=c.head_raise_inner_y,
                warped_size=c.warped_size, side_floor=c.side_floor,
                stamp_noise=c.stamp_noise,
                frame_residue_top=c.frame_residue_top,
                frame_residue_bottom=c.frame_residue_bottom,
                band_width=float(c.band[1] - c.band[0]),
            ))
        return {"column_geometry": GateManifest(
            page=page, admitted=page_ok, reject=page_reject, flags=page_flags,
            period=period, ref_w=ref_w, period_from_prior=period_from_prior,
            column_widths=widths, median_width=med_w, columns=recs, contract=CONTRACT)}
