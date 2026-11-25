"""2b 定字带左右边：竖直墨量投影找文字带两端，带外界行抹白。

五小步拆分（2026-11-25，`doc/2-切字/五小步.md`）从 `column_warp` 里分出来的一步，算法一字未改
（`impl.keben.column.band_strip` = `column_text_band` + `strip_column_rules`）。输入 2a 的去噪列图 `column_raw`，
输出每列文字带 `column_bands` 与界行抹白后的缓存列图 `column_banded`（尺寸不变，抹白而不是裁，列图坐标系不动）。
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, model_serializer

from ..core.spec import StepSpec, column_key, parse_key
from ..core.step import RunContext, Step, register_step
from ..impl.keben.column import band_strip
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

    @model_serializer(mode="wrap")
    def _drop_off_switches(self, handler):
        """缺省关的开关不进 dump：没开的书 `params_hash` 不变。"""
        d = handler(self)
        if isinstance(d, dict):
            for k in ("tight_rule_band", "inner_bar_span"):
                if not getattr(self, k):
                    d.pop(k, None)
        return d


def bar_kwargs(p: ColumnBandParams) -> dict:
    return {**({"bar_after_min_peak": TIGHT_INNER_BAR_PEAK, "first_valley": True} if p.tight_rule_band else {}),
            **({"inner_bar_span": True} if p.inner_bar_span else {})}


@register_step
class ColumnBandStep(Step):
    spec = StepSpec(
        id="column_band", title="2b 定字带左右边（竖直墨量投影、抹界行）", version="1.0", unit="column",
        consumes=("column_windows", "column_raw"),
        produces=("column_bands", "column_banded"),
        params=ColumnBandParams,
        code_deps=("open_guji_cv.seg.warp", "open_guji_cv.seg.profile", "open_guji_cv.impl.keben.column"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: ColumnBandParams = ctx.params_for(self)  # type: ignore[assignment]
        wins: PageWindows = ctx.product("column_windows", page)
        recs: list[ColumnBandRec] = []
        for w in wins.columns:
            key = column_key(page, w.col)
            raw = ctx.image("column_raw", key)
            _den, band, no_rules = band_strip(raw, p.ink_threshold, **bar_kwargs(p))
            ctx.cache.put(ctx.book.id, "column_banded", key, no_rules)
            recs.append(ColumnBandRec(col=w.col, band=(int(band[0]), int(band[1]))))
        return {"column_bands": PageBands(page=page, columns=recs)}

    def render(self, ctx: RunContext, kind_id: str, key: str) -> np.ndarray:
        page, col, _ = parse_key(key)
        if col is None:
            raise ValueError(f"{kind_id} 的键必须带列号: {key}")
        p: ColumnBandParams = ctx.params_for(self)  # type: ignore[assignment]
        _den, _band, no_rules = band_strip(ctx.image("column_raw", key), p.ink_threshold, **bar_kwargs(p))
        return no_rules
