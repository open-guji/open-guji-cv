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

页级 `reject` 只是给控制台看的汇总摘要（这道闸是列级闸，真正拦截靠逐列
`admitted`），2026-09-12 前有个漏洞：只在 `columns` 为空时才填，列非空但
全部被拒时留空，控制台显示"p1："后面什么都没有。现在：
- 若闸1（`border_detect_gate_manifest`）判定这页是 skip 类，直接写 L0，
  不用等 Step3 的 DP 结果——page_type 是事实性信息，只有闸1一个权威来源，
  这道闸直接查它（`ctx.product`），不经 Step2/Step3 转手抄一份。
- 否则若列非空但全部未过、且全部是「弹性 DP 无解」，写 **L0u「版式未支持」**
  （职名/目录类，见下）。
- 否则若列非空但全部未过，写一句汇总（"N 列全部未过"），不留空。

L0u「版式未支持」：为什么在这道闸判（2026-09-13）
------------------------------------------------
职名页/目录页每列字数不是版式格数且**逐列不同**，按 21 格先验切必然无解。
这不是故障，但此前与真异常混在「整页被拦（异常）」一个数字里——vol01 看着
40 页事故，真异常反被淹没。

**判定非得在 Step3**：闸1 的 `classify_page_type` 在切分前跑，只看得到灰度
统计，实测把 roster 31 页 / toc 47 页全归进 body（用户 2026-09-12 定
「职名页只有第三步才能查出来」，与代码实测一致）。

判据是「弹性 DP 无解的列占比」，**不是** `clustering/page_type.py` 里
`refine_page_type()` 那个「弹性列比例」。原卡本来打算给 v2 的 `cells` 补
`layout` 字段好复用老判据，核实后发现**那条路走不通**：`refine_page_type`
读的是切成功之后每列的 `layout`，而 v2 里职名页 44 页有 38 页整页一列都没
切出来（396 列只有 43 列 ok）——要判的恰恰是没有 cells 可看的页。于是把
观测对象从「切出来什么样」换成「切不出来」，实测分离反而是完全的
（294 页正文无解列恒为 0）。阈值论证与金标数字见 `page_type.py`。

**不细分 roster/toc**：toc 有 7 页与 roster 在这个量上完全重叠，分不开
（`refine_page_type` 也明说 toc 不判）。所以这一类只断言「非正文、现有先验
切不了」，不谎称能分文学类别。细分是 `keben_roster.yaml` 那件事。

判定写进产物（`unsupported_layout` / `n_unsupported_columns`），**不只在
前端算**——前端按 reject 前缀分桶只是显示层，判据要能被直接复核。

R2/R2s/R2x 的判据必须与 `eval/rulers.py` 算的是同一个量——两处共用
`eval.rulers.classify_boundary`，不再各写一份（Step0 闸 0 曾经栽在
"文档说的量"和"代码实际算的量"对不上）。
"""

from __future__ import annotations

from pydantic import BaseModel

from ..clustering.page_type import UNSUPPORTED_LAYOUT_ERROR, unsupported_layout_columns
from ..core.spec import GateLevel, GateSpec, StepSpec
from ..core.step import RunContext, Step, attach_gate, register_step
from ..eval.rulers import _col_profile, classify_boundary
from ..products.kinds.border_detect_gate import BorderDetectGateManifest
from ..products.kinds.cells import PageCells
from ..products.kinds.row_segment_gate import RowSegmentGateColumn, RowSegmentGateManifest


class RowSegmentGateParams(BaseModel):
    expected_slots: int | None = None   # None = Book.chars_per_line
    slot_tol: int = 1                   # n_body_slots 与版式格数的容许偏差
                                         # （effective_body_slots 正当下调 1 格）
    #: L4 碎格判据（2026-09-18）：格高低于 `sliver_ratio × period` 就算碎格。
    #: 0.35 的依据——bxgb 全书 20446 格的格高分布里，正常格最低也在 0.7·period
    #: 上下（DP 的 `lo_ratio` 硬约束卡着），而实测命中的 16 个碎格是 11~25px
    #: 对 period≈72，比值 0.15~0.35，中间空着一大段。取 0.35 落在空档上沿，
    #: 两边都有余量。**只 flag 不 block**：碎格列的字多数仍切得对（p53 逐列
    #: 看图确认「焚香致敬」四字各一格），拦下来会连累整列作废。
    sliver_ratio: float = 0.35


@register_step
class RowSegmentGateStep(Step):
    spec = StepSpec(
        id="row_segment_gate", title="Step3→4 交接闸", version="1.3", unit="column",
        consumes=("cells", "border_detect_gate_manifest"), produces=("row_segment_gate_manifest",),
        params=RowSegmentGateParams,
        code_deps=("open_guji_cv.eval.rulers", "open_guji_cv.clustering.page_type"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: RowSegmentGateParams = ctx.params_for(self)  # type: ignore[assignment]
        expected = p.expected_slots or ctx.book.chars_per_line
        # `border_detect_gate_manifest` 在 consumes 里——引擎的 fingerprint
        # 已经保证跑到这里时它一定存在（历史上没跑过闸1的页会先被引擎判
        # 「上游缺失」而不会执行到这一行，需要先补跑闸1，不在这里旁路兜底）。
        page_type_gate: BorderDetectGateManifest = ctx.product(
            "border_detect_gate_manifest", page)
        skip_reject = (
            [f"L0：闸1判定页型「{page_type_gate.page_type}」，非正文，已跳过切列"]
            if page_type_gate.page_type_policy == "skip" else [])
        if not ctx.has_product("cells", page):
            return {"row_segment_gate_manifest": RowSegmentGateManifest(
                page=page, admitted=False,
                reject=skip_reject or ["L1：上游 cells 产物缺失"])}
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

            # L4 碎格（2026-09-18，格子级——闸3 此前只有页级/列级两层）。
            # DP 凑格数时会造出十几像素的格，它让后面每格往上挤、累积成相位
            # 错位，而**列格数是对的，逐列字数对账查不出来**
            # （`row_boundaries.BLANK_MIN_RATIO` 注释记过这个病）。
            sliver: list[int] = []
            if not reject and cc.ok and (cc.period or 0) > 0:
                lim = p.sliver_ratio * cc.period
                for k, cell in enumerate(cc.cells):
                    if (cell.y1 - cell.y0) < lim:
                        sliver.append(cell.slot)
            if sliver:
                flags.append(
                    f"L4：{len(sliver)} 个碎格（高 < {p.sliver_ratio:g}×格高），"
                    f"slot {sliver}——DP 凑格数造的，会让整列相位往上挤")

            recs.append(RowSegmentGateColumn(
                col=cc.col, admitted=not reject, reject=reject, flags=flags,
                n_body_slots=cc.n_body_slots if cc.ok else None,
                n_r2=n_r2, n_r2s=n_r2s, n_r2x=n_r2x,
                sliver_slots=sliver,
            ))

        page_admitted = any(c.admitted for c in recs) if recs else False
        # 「版式未支持」：这页不是正文版式，现有 21 格先验切不了（职名/目录）。
        # 判据与阈值论证见 `clustering/page_type.py` 的 UNSUPPORTED_LAYOUT_ERROR
        # 一节——294 页正文实测无解列恒为 0，所以只要**整页一列都没过**且无解
        # 列是「弹性 DP 无解」这一种，就判它。
        #
        # 为什么要求「整页无一列过」：单列无解在正文页上确实没出现过，但真出了
        # 故障也会表现成个别列无解，那是该查的。要求整页才判，等于把"偶发单列
        # 失败"留在异常里——存疑一律归异常，与 page_type.py 那条"存疑一律归
        # body"的方向性代价同向（宁可多查一页，不可静默吞掉一页）。
        n_unsupported = unsupported_layout_columns(
            [c.model_dump() for c in cells.columns])
        is_unsupported = (
            not skip_reject and bool(recs) and not page_admitted
            and n_unsupported == len(recs))
        if skip_reject:
            page_reject = skip_reject
        elif not recs:
            page_reject = ["L1：本页无 cells 记录"]
        elif is_unsupported:
            # L0u 与闸1 的 L0 分开：L0 是「闸1 已判非正文、根本没切」，
            # L0u 是「切了，但这页的版式现有先验支持不了」。控制台按前缀
            # 分桶，两者都不进「整页被拦（异常）」。
            page_reject = [
                f"L0u：版式未支持——{n_unsupported} 列全部「{UNSUPPORTED_LAYOUT_ERROR}」，"
                f"每列字数非 {expected} 且逐列不同（职名/目录类），"
                f"非故障，待 keben_roster.yaml 支持"]
        elif not page_admitted:
            # 2026-09-12 修复：原先 `columns` 非空但全部被拒时这里留空——
            # 控制台 ProgressGatePanel 只显示页级 reject，会显示成"p1："
            # 后面什么都没有，看不出这页为什么整页没有一列过闸。这道闸是
            # 列级闸（`unit="column"`），列级原因已经在各自 `columns[].reject`
            # 里，这里只给一句页级摘要，不重复照抄。
            page_reject = [f"L1：本页 {len(recs)} 列全部未过（各列拒因见列级 reject）"]
        else:
            page_reject = []
        return {"row_segment_gate_manifest": RowSegmentGateManifest(
            page=page, admitted=page_admitted, reject=page_reject, columns=recs,
            unsupported_layout=is_unsupported,
            n_unsupported_columns=n_unsupported)}


# 挂到 Step3（row_segment）出口——levels 的 desc 只描述层次，不重复具体阈值数字
# （阈值在 RowSegmentGateParams 里，写两处会漂）。
attach_gate("row_segment", GateSpec(
    id="row_segment_gate", unit="column", on_fail="block",
    levels=(
        GateLevel(id="L0", unit="page",
                  desc="闸1是否判定这页页型为 skip 类——是则页级直接拒收，"
                       "不看列级 DP 结果"),
        GateLevel(id="L0u", unit="page",
                  desc="是否「版式未支持」（整页各列都因弹性 DP 无解而被拒）——"
                       "职名/目录类，非故障，与真异常分开记"),
        GateLevel(id="L1", unit="column", desc="DP 是否有解"),
        GateLevel(id="L1", unit="column",
                  desc="格数是否偏离版式格数超过容许范围（非 effective_body_slots 的正当下调）"),
        GateLevel(id="L2", unit="column",
                  desc="R2 可改善格线数——flag，不拦（该修但不算作废这一列）"),
        GateLevel(id="L2", unit="column",
                  desc="R2s 真粘连格线数——flag，不拦（图像极限，不算错）"),
        GateLevel(id="L4", unit="cell",
                  desc="碎格：格高远小于一格——flag，不拦（列里多数字仍切得对）"),
    ),
))
