"""2b 定字带左右边：竖直墨量投影找文字带两端，带外界行抹白。

五小步拆分（2026-11-25，`doc/2-切字/五小步.md`）从 `column_warp` 里分出来的一步。左右切点缺省用 `seg.side_cut`
（`side_cut`，2026-11-25 起：切点以外再抹白，文字带数值仍用旧算法）；关掉＝旧算法（`impl.keben.column.band_strip` = `column_text_band` + `strip_column_rules`）。输入 2a 的去噪列图 `column_raw`，
输出每列文字带 `column_bands` 与界行抹白后的缓存列图 `column_banded`（尺寸不变，抹白而不是裁，列图坐标系不动）。
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, model_serializer

from ..core.spec import StepSpec, column_key, parse_key
from ..core.step import RunContext, Step, register_step
from ..impl.keben.column import band_strip
from ..seg.side_cut import side_cut_points
from ..products.kinds.columns import ColumnBandRec, PageBands, PageWindows

#: `tight_rule_band`：内侧孤立窄条峰到这么高才当第二道线（写本「以」的左竖一条 240 行里峰 0.16~0.33）
TIGHT_INNER_BAR_PEAK = 0.5


class ColumnBandParams(BaseModel):
    ink_threshold: int = 128
    tight_rule_band: bool = False
    """两侧界行判带收紧（写本开，史記）：贴边界行取衰减后的第一个谷（`column_text_band` first_valley），
    内侧孤立窄条峰到 TIGHT_INNER_BAR_PEAK 才当第二道线抹（缺省 0.10，殿本页边列内框淡到 0.12）。缺省关＝殿本旧行为。
    起因：写本字贴着界行写，「以」的左竖细高、跟右半「人」之间的缝比界行与字之间的缝还白，
    判带取窗口最低点、或把它当内框，都连界行一起抹白，Step4 拿到的字就缺一笔（SJ r5，02:27:1:4b、02:112:2:2b）。
    （2026-11-25 前叫 `column_warp.tight_rule_band`，册配置里旧名仍有效，见 `core/pipeline.LEGACY_PARAM_HOMES`。）"""
    inner_bar_span: bool = False
    """贴边界行内侧的「孤立窄条」要像线才抹（全唐文开）：离边超过 0.13 列宽、本横条里有墨的行不到一半的，
    是字贴着界行的竖笔，不当第二道线（`column_text_band` inner_bar_span）。缺省关＝旧行为。
    起因：全唐文「十」的竖、「恪」的忄贴着界行，`strip_column_rules` 按 240 行横条判带，把它们当内框连界行一起抹白，
    Step4 拿到「亠」（001:121:1:6a、001:106:9:6a、014:108:3，台账 R033／R038）。"""

    side_cut: bool = True
    """左右切掉位置用新算法（`seg.side_cut`，2026-11-25 用户定、缺省开）：只取上下边框之间（各让 60 行）的行做竖直墨量
    投影，认出框线后在框线内侧 15% 列宽内取第一个够低处、往里缩 2px，切点以外整列抹白（在旧算法抹界行的基础上再抹），
    切点记在 `column_bands` 的 `cut`。**文字带 `band` 仍是旧算法的值**：2d 切字对字带宽度很敏感——史記 42 册测试集
    带每边窄 3px 列全对 287→264、窄 1px 也 →274，把带的数值换回旧值、列图照用新抹的，切线就和原来一样（CV2 11-25）。
    关＝完全旧行为。以旧算法当金标比 4 套书 1460 列，开 CV1 的 `vline_track`+`outer_bar` 后不一致 60 列，新算法多丢墨 6 列
    （史記卷首页噪点 4、脉经 1 列笔尖）；已知短处：点线／双线里的细内线（墨占比 < 0.3）认不出（全唐文 053:87:6、
    053:148:9），这种列靠旧算法那一遍抹。上下边框之间不足 200 行时只用旧算法。"""

    @model_serializer(mode="wrap")
    def _drop_off_switches(self, handler):
        """缺省关的开关不进 dump：没开的书 `params_hash` 不变。"""
        d = handler(self)
        if isinstance(d, dict):
            for k in ("tight_rule_band", "inner_bar_span"):
                if not getattr(self, k):
                    d.pop(k, None)
        return d


def band_and_strip(p: ColumnBandParams, w, raw: np.ndarray
                   ) -> tuple[tuple[int, int], tuple[int, int] | None, np.ndarray]:
    """一列的文字带 `band`（半开，旧算法）、左右切点 `cut`（半开，`side_cut` 关或算不出为 None）与抹白后的列图。"""
    den, band, no_rules = band_strip(raw, p.ink_threshold, **bar_kwargs(p))
    cut = None
    if p.side_cut:
        cut = side_cut_points(den, w.border_top_in_column, w.border_bottom_in_column, p.ink_threshold)
        if cut is not None:
            no_rules = no_rules.copy()
            no_rules[:, :cut[0]] = 255
            no_rules[:, cut[1]:] = 255
            cut = (int(cut[0]), int(cut[1]))
    return (int(band[0]), int(band[1])), cut, no_rules


def bar_kwargs(p: ColumnBandParams) -> dict:
    return {**({"bar_after_min_peak": TIGHT_INNER_BAR_PEAK, "first_valley": True} if p.tight_rule_band else {}),
            **({"inner_bar_span": True} if p.inner_bar_span else {})}


@register_step
class ColumnBandStep(Step):
    spec = StepSpec(
        id="column_band", title="2b 定字带左右边（竖直墨量投影、抹界行）", version="1.1", unit="column",
        consumes=("column_windows", "column_raw"),
        produces=("column_bands", "column_banded"),
        params=ColumnBandParams,
        code_deps=("open_guji_cv.seg.warp", "open_guji_cv.seg.profile", "open_guji_cv.impl.keben.column",
                   "open_guji_cv.seg.side_cut"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: ColumnBandParams = ctx.params_for(self)  # type: ignore[assignment]
        wins: PageWindows = ctx.product("column_windows", page)
        recs: list[ColumnBandRec] = []
        for w in wins.columns:
            key = column_key(page, w.col)
            raw = ctx.image("column_raw", key)
            band, _cut, no_rules = band_and_strip(p, w, raw)
            ctx.cache.put(ctx.book.id, "column_banded", key, no_rules)
            recs.append(ColumnBandRec(col=w.col, band=band))
        return {"column_bands": PageBands(page=page, columns=recs)}

    def legacy_strip(self, ctx: RunContext, raw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """旧包重放（CV4 算法待办 #13，2026-11-27）：拆步前旧产物包（各书钉 0.7.x 线的 main 包）没有 `column_bands`，
        2c `column_end` 现算列图时经这里按拆步前 `column_warp` 的 `clean_column` 前半算 `(去噪图, 界行抹白后的图)`，
        只在内存里，不写包、不进 `column_banded` 缓存。本步现行参数（写本 `tight_rule_band`、全唐文 `inner_bar_span`）照用，
        `side_cut`（拆分后 #1900 才加、缺省开）不用——旧包的列图与格坐标都是没有它时出的。"""
        p: ColumnBandParams = ctx.params_for(self)  # type: ignore[assignment]
        denoised, _band, no_rules = band_strip(raw, p.ink_threshold, **bar_kwargs(p))
        return denoised, no_rules

    def render(self, ctx: RunContext, kind_id: str, key: str) -> np.ndarray:
        page, col, _ = parse_key(key)
        if col is None:
            raise ValueError(f"{kind_id} 的键必须带列号: {key}")
        p: ColumnBandParams = ctx.params_for(self)  # type: ignore[assignment]
        w = next(c for c in ctx.product("column_windows", page).columns if c.col == col)
        return band_and_strip(p, w, ctx.image("column_raw", key))[2]
