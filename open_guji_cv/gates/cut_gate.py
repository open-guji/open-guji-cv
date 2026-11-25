"""2 切字·出口闸：只在最后调用一次，读 2a–2e 全部产物，只出裁决，不挡任何中间步。

2026-11-25 用户定：出口闸有自己的接口，永远在最后才调用。以前的 `column_gate`（挂在 2a 后、挡列）与
`row_segment_gate`（挂在字间切分后）并到这里，挂在 `cell_shrink`（切字大步的最后一步）出口：
- 列级质量判据（L1 列数、L1c 列宽、L1n 列窄、L2 界行残墨、L2b 印章噪点、L4e 框线残留、double_width、夹注豁免）
  判据一字未改，输入用 `column_geometry`（计算量）＋ 2a–2c 产物；产物仍叫 `gate_manifest`（形状不变，下游读者不用改）。
  **结构性不切**（页型 skip、非正文列位、表格列、页级周期估不出）在 `column_geometry` 里已定，这里照抄进拒因。
- 格级判据（DP 有解、格数、碎格、R2/R2s 等）仍由 `row_segment_gate` 的实现算，产物 `row_segment_gate_manifest`
  ——它那个 Step 注册着、但不再挂在 `row_segment` 上，由本闸在最后调用。
"""

from __future__ import annotations

import statistics

import numpy as np
from pydantic import BaseModel, model_serializer

from ..core.book import _expand_pages
from ..core.spec import GateLevel, GateSpec, StepSpec, column_key
from ..core.step import STEPS, RunContext, Step, attach_gate, register_step
from ..impl.keben import jiazhu_split
from ..seg.side_cut import side_cut_points
from ..impl.keben.column_pair_merge import has_pair_merged
from ..products.kinds.columns import PageWindows
from ..products.kinds.gate import GateColumn, GateManifest
from ..steps._colview import merged_windows
from ..steps.column_geometry import TABLE_COLUMN_REJECT
from .column_gate import COLUMN_GATE_SPEC
from .row_segment_gate import ROW_SEGMENT_GATE_SPEC



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




class CutGateParams(BaseModel):
    expected_cols: int | None = None    # None = Book.expected_cols
    expected_cols_pages: dict[int, int] = {}
    """按页列数（2026-11-12，殿本 vol01 p100：图上 10 列、版框只探出 9 列，参校本质检）：`{页: 本页列数}`，覆盖册级 `expected_cols`。
    职名页、个别页列数与册级不同时用；一般同 `vline_overrides` 配用（给出本页全部竖线）。border_detect、border_detect_gate、
    column_gate 三处都要写同一张表。缺省空，空时不进参数 dump，产物与加字段前逐字节相同。"""
    count_mode: str = "exact"           # exact：列数必须等于版式列数 | detected：列数由 Step1 探出，只要求 ≥1（现代链）
    width_tol: float = 0.15
    side_floor_max: float = 0.045
    stamp_noise_max: float = 0.007      # L2b：见 column_projection.STAMP_NOISE_MAX 的标定记录
    jiazhu_frac_min: float = jiazhu_split.COLUMN_FRAC_T  # 夹注列豁免门槛，见 L1c/L2 的豁免说明
    #: 两倍宽的列不享夹注豁免（overview#447）。0 = 关（缺省，产物逐字节不变）；
    #: >0 = 本列文字带宽 ≥ 此比例×本页中位宽时，**撤销夹注列豁免并拒收待审**。
    #: 夹注列是「一列里并排两行小字」，宽度仍是一列；宽到两倍的只可能是两列正文被并成一列
    #: （vol04 p216c6、p218c2，中间那条界行被当夹注缝）。建议 1.8。
    double_width_ratio: float = 0.0
    tier: str = "gate"                  # gate | gold（gold 需接数据集，P2）
    # 名字像 guardrail 配置，实际不是：这只是一个尚未生效的枚举参数，不落
    # 文件、不是名单，按 doc/data-taxonomy.md 的判断标准仍是普通算法参数
    # （2026-09-11 Step2 数据盘点核实时发现容易误读，记一笔避免下次又查一遍）。
    ink_threshold: int = 128
    frame_residue_min_run: int = 3
    #: L1n 列宽下限（overview#427）：文字带宽 < 本页中位数 × 此比例 → flag `column_narrow`。
    #: 四庫 vol04 p63c1/p80c5/p80c6/p217c2/p217c3 这 5 列切进了字里，列图只剩笔画边缘，
    #: 下游认出一串乱码（context 放行 93 格）；vol04 全书 1962 列里 <0.75 的正好这 5 列。
    #: vol05–10 再命中 18 列，多数同样是乱码，但「X卷採進本」这类本来就窄的小字行、vol03 p49c7/c8
    #: 窄列也读得对——所以缺省只标记；书里确认窄列都是切坏时，`narrow_reject` 打开整列拒。
    narrow_ratio: float = 0.75
    narrow_reject: bool = False
    #: **点名页直接用书级 period 先验**（GUJI-364／GUJI-622，vol01 p196）。缺省空 = 关，
    #: 关时不进参数指纹、产物逐字节不变。列在这里的页不估页级周期，直接用 `period_prior`，
    #: 记 flag `period_fallback`。用在目录页这类字稀的页：自相关最大值卡在窗口下界
    #: （vol01 p196 估出 80px＝115×0.7，真值≈115），Step3 拿它当格距「弹性 DP 无解」，整列 0 格。
    #: 写法同 `row_segment.roster_pages`：`params: {column_gate: {period_prior_pages: [196]}}`。
    table_cols: dict[int, list[int | str]] = {}
    #: L2c 自检（2026-11-25，用户定）：当前左/右切点比「框内缘之后最少墨处」（`side_cut_points`，算时忽略上下
    #: 边框前后各 `cut_probe_margin` 行）更靠里超过此像素数 → 拒收 `cut_too_inward`。0 = 关。
    #: 标定：全唐文 053 360 列、脉经 420 列、殿本 vol01 360 列，切点与最少墨处的偏差分位 99% 均 ≤0，
    #: 超 6px 只有全唐文 053 p148c9 左侧一列（30px，切进字里）；10 留足余量。
    cut_inward_max_px: float = 10.0
    cut_probe_margin: int = 60


    @model_serializer(mode="wrap")
    def _drop_off_overrides(self, handler):
        d = handler(self)
        if isinstance(d, dict):
            if not self.expected_cols_pages:
                d.pop("expected_cols_pages", None)
            if not self.table_cols:
                d.pop("table_cols", None)
        return d


@register_step
class CutGateStep(Step):
    spec = StepSpec(
        id="cut_gate", title="2 切字出口闸（列级质量＋格级判据）", version="1.0", unit="column",
        consumes=("column_geometry", "column_windows", "column_bands", "column_ends", "column_image", "column_raw", "cells",
                  "border_detect_gate_manifest"),
        optional_consumes=("line_index",),
        produces=("gate_manifest", "row_segment_gate_manifest"),
        params=CutGateParams,
        code_deps=("open_guji_cv.impl.keben.column_pair_merge", "open_guji_cv.gates.row_segment_gate", "open_guji_cv.seg.side_cut",
                   "open_guji_cv.impl.keben.jiazhu_split", "open_guji_cv.steps._colview"),
        book_deps=("period_prior", "expected_cols", "chars_per_line"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: CutGateParams = ctx.params_for(self)  # type: ignore[assignment]
        geom: GateManifest = ctx.product("column_geometry", page)
        wins: PageWindows = merged_windows(ctx, page)
        cols = wins.columns
        gcols = {g.col: g for g in geom.columns}
        expected = p.expected_cols_pages.get(page) or p.expected_cols or ctx.book.expected_cols
        page_gate1 = ctx.product("border_detect_gate_manifest", page)
        if has_pair_merged(page_gate1.flags) and page_gate1.expected_cols == expected - 1:
            expected = page_gate1.expected_cols
        widths, med_w = list(geom.column_widths), geom.median_width
        period, ref_w = geom.period, geom.ref_w
        tc_spec = p.table_cols.get(page) if p.table_cols else None
        table_cols = set(_expand_pages(list(tc_spec))) if tc_spec else set()
        page_reject = list(geom.reject)
        if page_gate1.page_type_policy != "skip" and cols and p.count_mode != "detected" and len(cols) != expected:
            page_reject.append(f"column_count：只探出 {len(cols)} 列（版式应为 {expected}）")
        page_ok = not page_reject
        page_flags = list(geom.flags)
        wide_cols = {c.col: (w - med_w) / med_w
                     for c, w in zip(cols, widths)
                     if med_w and abs(w - med_w) > p.width_tol * med_w}
        non_body: dict[int, tuple[str, str]] = {}
        for g in geom.columns:
            if any(r.startswith(TABLE_COLUMN_REJECT) for r in g.reject):
                non_body[g.col] = ("table", "")
            elif any(r.startswith("non_body_column") for r in g.reject):
                non_body[g.col] = ("margin", "")

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
            reasons.extend(r for r in gcols[c.col].reject if not r.startswith("页级未过"))
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
            double_wide = (p.double_width_ratio > 0 and med_w and c.col not in non_body
                           and (c.band[1] - c.band[0]) >= p.double_width_ratio * med_w)
            if double_wide:
                # 先于豁免：两倍宽不是夹注列，豁免撤销；拒收让人看，Step3 不对它硬切。
                is_jiazhu_col = False
                reasons.append(
                    f"double_width：本列文字带宽 {c.band[1] - c.band[0]:.0f}px 是本页中位数 "
                    f"{med_w:.0f}px 的 {(c.band[1] - c.band[0]) / med_w:.1f} 倍，疑为两列正文并成一列"
                    "（夹注列宽仍是一列，不享豁免）")
            if is_jiazhu_col:
                flags.append(f"column_width/side_ink 豁免：本列 {jz_frac:.0%} 的非空白格呈双列小字，"
                             "判为夹注列（两侧顶满列宽是版式如此，不是列窗没对）")
            if c.col in wide_cols and not is_jiazhu_col:
                band_w = c.band[1] - c.band[0]
                # flag 级，不进 reject（2026-09-19 从 block 降下来，与 side_ink 同一轮）。
                # 判词是「多半圈进了界行/夹注双栏」——**「多半」不足以 block**。
                # vol02 实测被它拦下的 4 列（p3c1 +31%、p160c4 +16%、p177c2 +39%、
                # p178c4 +25%）逐列看图：全是干净的单列正文，宽只是因为它们是
                # 边列、窗口带进了版框内侧的余白。强行送进 Step3 四列全部有解、
                # 切出满格 21 slot。
                flags.append(f"column_width：本列文字带宽 {band_w}px 偏离本页中位数 "
                             f"{med_w:.0f}px {wide_cols[c.col]:+.0%}"
                             "（可能圈进了界行/夹注双栏，flag 不算错）")
            band_w = c.band[1] - c.band[0]
            if med_w and band_w < p.narrow_ratio * med_w and not is_jiazhu_col \
                    and c.col not in non_body:
                msg = (f"column_narrow：本列文字带宽 {band_w:.0f}px 不到本页中位数 {med_w:.0f}px 的 "
                       f"{p.narrow_ratio:.0%}（{band_w / med_w:.0%}），列界多半切进了字里")
                (reasons if p.narrow_reject else flags).append(msg)
            if c.side_floor > p.side_floor_max and not is_jiazhu_col:
                # flag 级，不进 reject（2026-09-19 从 block 降下来）。判据本身没错——
                # vol02 58 条 column-warp 金标上 >0.045 命中 1/3 mixed、0/55 clean 误伤——
                # 错的是**后果**：block 把整列丢掉，而这一层量的「两侧还有墨」多半是
                # 界行没剥干净或纸面污渍，**不影响 Step3 切字缝**。vol02 实测被它拦下的
                # 21 列（p3/160/177/178/188）**强行送进 Step3 全部 21/21 有解**，每列
                # 切出满格 21 slot、12~21 个字格——等于白丢了约 400 个字。
                # 与 `stamp_noise` / `frame_residue` 同一纪律：没验证过「超标必错」的
                # 判据只标记、不硬拦（那两条的注释里写着同样的理由）。
                flags.append(f"side_ink：两侧最低墨占比 {c.side_floor:.4f} > {p.side_floor_max}"
                             "（界行没剥干净或纸面污渍，flag 不算错）")
            if p.cut_inward_max_px > 0 and c.col not in non_body and not is_jiazhu_col:
                try:
                    raw = ctx.image("column_raw", column_key(page, c.col))
                except Exception:
                    raw = None
                pts = (side_cut_points(raw, c.border_top_in_column, c.border_bottom_in_column, p.ink_threshold,
                                       p.cut_probe_margin) if raw is not None else None)
                if pts is not None:
                    d_l, d_r = c.band[0] - pts[0], pts[1] - c.band[1]
                    if max(d_l, d_r) > p.cut_inward_max_px:
                        side = "左" if d_l >= d_r else "右"
                        reasons.append(
                            f"cut_too_inward：{side}切点比框内缘之后最少墨处靠里 {max(d_l, d_r):.0f}px"
                            f"（> {p.cut_inward_max_px:g}px），疑似切进字里")
            if c.stamp_noise > p.stamp_noise_max:
                # flag 级，不进 reject：只在 115 列金标上验证过背景印章这一种机制，
                # 未见过的书页上有没有误伤先例不确定，先标记攒人审证据，不硬拦。
                flags.append(f"stamp_noise：整列噪点密度 {c.stamp_noise:.4f} > {p.stamp_noise_max}"
                             "（疑似背景印章污染，flag 不算错）")
            # 端部残留版框墨：`column_border_trim` 判「怎么削」，这一条验「削干净没有」。
            # flag 不 block，三条理由：(1) b 档那 9 个端口是**已知的图像极限**
            # （框与字粘连成一个连通体，按红线不能剥，见 frame-strip README），
            # 拦下来等于永久卡死；(2) 框墨留在列图里不影响切分本身——Step3 切的是
            # 字缝，框墨在格子边缘，真正受影响的是 Step4 字块质量，那步有
            # `strip_frame_debris`；(3) 闸的既有纪律就是「图像极限只标记不拦」。
            #
            # **非正文列不标**（2026-09-19，实跑定的）：版心（书口）那一列本来
            # 就横贯着版框线，判据当然命中，可「版心里有框墨」不是缺陷、也没人
            # 要去修它。bxgb 全书 53 个命中里 43 个是 c10 版心，占 81%——照单
            # 全收等于让裁决台 5 条里有 4 条是废话，真正要看的 10 条正文列反而
            # 被淹掉。这一列已经由 `non_body_column` 拒收，不必再叠一个 flag。
            residue = [] if c.col in non_body else [
                (end, run) for end, run in
                (("上", c.frame_residue_top), ("下", c.frame_residue_bottom))
                if run >= p.frame_residue_min_run]
            if residue:
                flags.append("frame_residue：" + "、".join(
                    f"{end}端残留满宽段 {run} 行" for end, run in residue)
                    + f"（≥{p.frame_residue_min_run} 行判为版框没削干净，flag 不算错）")
            if p.tier == "gold":
                reasons.append("human_verdict：金标准入尚未接入（P2）")
            if c.col in table_cols and c.col in non_body and non_body[c.col][0] == "table":
                # 半文半表页的表格列只留拒因（L0t），不叠列宽、侧墨、噪点这类 flag
                flags = []
            recs.append(gcols[c.col].model_copy(update={
                "admitted": not reasons, "reject": reasons, "flags": flags, "tier": p.tier}))
        manifest = GateManifest(
            page=page, admitted=page_ok, reject=page_reject, flags=page_flags,
            period=period, ref_w=ref_w, period_from_prior=geom.period_from_prior,
            column_widths=widths, median_width=med_w, columns=recs, contract=geom.contract)
        out: dict[str, BaseModel] = {"gate_manifest": manifest}
        out.update(STEPS["row_segment_gate"].run_page(ctx, page))     # 格级判据，实现沿用
        return out


CUT_GATE_SPEC = GateSpec(
    id="cut_gate", unit="column", on_fail="block",
    levels=COLUMN_GATE_SPEC.levels + (
        GateLevel(id="L2c", unit="column",
                  desc="左/右切点是否比框内缘之后最少墨处靠里过多（算时忽略上下边框前后各一段）——拒收，疑似切进字里",
                  name="cut_too_inward"),
    ) + ROW_SEGMENT_GATE_SPEC.levels,
)
attach_gate("cell_shrink", CUT_GATE_SPEC)
