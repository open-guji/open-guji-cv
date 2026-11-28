"""borders：Step1 边框探测的产物（numeric）。

镜像 `utils/border_geometry.BorderDetectionResult`——它本身就用右上原点（x 向左、
列从右起），所以这里的坐标空间就是规范空间 raw_page_px@top-right，不换算。
`BorderDetectionResult` 没有序列化方法，双向转换在这里。
**折线的 k2/k3/y1/y2 必须一起存**，否则三段页退化成第一段外推的直线且无法还原。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_serializer

from ...core.spec import RAW_TR, ProductKindSpec
from ...core.step import register_kind
from ...seg.frame_types import (BorderDetectionResult, HeadRaiseBorder, HLine,
                                      VLine)


class HLineRec(BaseModel):
    y_at_right: float   # 横线在规范空间右端（x_tr=0）处的 y，px
    slope: float   # 横线斜率 dy/dx_tr
    kind: str   # 线的来源或类别（探测路径名，如直线拟合、墨条、估位）

    @classmethod
    def of(cls, h: HLine) -> "HLineRec":
        return cls(y_at_right=float(h.y_at_right), slope=float(h.slope), kind=h.kind)

    def to_hline(self) -> HLine:
        return HLine(y_at_right=self.y_at_right, slope=self.slope, kind=self.kind)


class VLineRec(BaseModel):
    x_at_top: float   # 竖线在页顶（y=0）处的 x_tr，规范空间 px
    slope: float   # 竖线斜率 dx_tr/dy（折线时为第一段）
    k2: float | None = None   # 折线第二段斜率；直线为空
    k3: float | None = None   # 折线第三段斜率；两段或直线为空
    y1: float | None = None   # 第一折点 y；直线为空
    y2: float | None = None   # 第二折点 y；直线为空
    segments: int = 1   # 折线段数（1＝直线，3＝三段折线）

    @classmethod
    def of(cls, v: VLine) -> "VLineRec":
        return cls(x_at_top=float(v.x_at_top), slope=float(v.slope),
                   k2=None if v.k2 is None else float(v.k2),
                   k3=None if v.k3 is None else float(v.k3),
                   y1=None if v.y1 is None else float(v.y1),
                   y2=None if v.y2 is None else float(v.y2),
                   segments=int(v.segments))

    def to_vline(self) -> VLine:
        return VLine(x_at_top=self.x_at_top, slope=self.slope,
                     k2=self.k2, k3=self.k3, y1=self.y1, y2=self.y2)


class HeadRaiseRec(BaseModel):
    col: int   # 抬头列号（右→左，从 1 起）
    inner_y: float   # 抬头处内框线 y，规范空间 px
    outer_y: float   # 抬头处外框线 y，规范空间 px
    estimated: bool = False   # 外框 y 是按规则估的、不是量到的

    @classmethod
    def of(cls, h: HeadRaiseBorder) -> "HeadRaiseRec":
        return cls(col=int(h.col), inner_y=float(h.inner_y), outer_y=float(h.outer_y),
                   estimated=bool(h.estimated))

    def to_hr(self) -> HeadRaiseBorder:
        return HeadRaiseBorder(col=self.col, inner_y=self.inner_y, outer_y=self.outer_y,
                               estimated=self.estimated)


class Borders(BaseModel):
    width: int   # 原图宽 px
    height: int   # 原图高 px
    expected_cols: int   # 册配置给的正文列数（每半页）
    top: HLineRec   # 上内版框线
    bottom: HLineRec   # 下内版框线
    verticals: list[VLineRec]                    # 右→左，N+1 条
    verticals_straight: list[VLineRec] = Field(default_factory=list)   # 折线拟合前的直线
    head_raise: list[HeadRaiseRec] = Field(default_factory=list)   # 抬头框阶梯（有抬头的列各一条），无则空表
    top_outer_offset: float | None = None   # 上外框线到上内框线的距离 px；没量到为空
    bottom_outer_offset: float | None = None   # 下外框线到下内框线的距离 px；没量到为空
    # "double" / "single"（單邊框）/ "none"；旧产物缺省 None。见 BorderDetectionResult。
    top_frame_kind: str | None = None   # 上框型 double｜single｜none；旧产物为空
    bottom_frame_kind: str | None = None   # 下框型，同上
    top_bar_extent: float | None = None   # 上粗外框条的厚度 px；没有为空
    bottom_bar_extent: float | None = None   # 下粗外框条的厚度 px；没有为空
    top_outer_estimated: bool = False   # 上外框线位置是估的
    bottom_outer_estimated: bool = False   # 下外框线位置是估的
    bottom_pushed: float = 0.0   # 下框被字挤下移的像素数（0＝没动）
    vlines_snapped: int = 0   # 被吸到淡界行细峰上的竖线条数
    v_outer_side: str | None = None   # 左右外框在哪一侧（纸边侧）left｜right；没量到为空
    v_outer_offset: float | None = None   # 侧外框线到内框线的距离 px；没量到为空
    v_outer_estimated: bool = False
    """规则（册配置 `side_frame`）说该有外框、这页没量到而按 `outer_gap.side` 估位。False **不落盘**、True 才落盘
    （同 `cells.alt_columns`），没用新规则的老册产物逐字节不变；读回缺省 False。"""
    vline_segments: int = 1   # 竖线中折线最多的段数
    bend_w80_med: float | None = None   # 折线弯曲宽度（沿线 80% 内偏离直线）的中位数 px；全直线为空
    bend_w80_max: float | None = None   # 折线弯曲宽度最大值 px；全直线为空
    # 与 verticals 一一对应；True = 网格模式下该槽位没探到细线、按几何插值
    # （见 `find_vertical_lines_grid`）。自由模式 / 旧产物为空或全 False。
    vline_filled: list[bool] = Field(default_factory=list)   # 与 verticals 一一对应；True＝该槽位没探到细线、按几何插值

    @classmethod
    def from_result(cls, r: BorderDetectionResult, expected_cols: int) -> "Borders":
        return cls(
            width=int(r.width), height=int(r.height), expected_cols=int(expected_cols),
            top=HLineRec.of(r.top), bottom=HLineRec.of(r.bottom),
            verticals=[VLineRec.of(v) for v in r.verticals],
            verticals_straight=[VLineRec.of(v) for v in (r.verticals_straight or [])],
            head_raise=[HeadRaiseRec.of(h) for h in (r.head_raise or [])],
            top_outer_offset=_f(r.top_outer_offset), bottom_outer_offset=_f(r.bottom_outer_offset),
            top_frame_kind=r.top_frame_kind, bottom_frame_kind=r.bottom_frame_kind,
            top_bar_extent=_f(r.top_bar_extent), bottom_bar_extent=_f(r.bottom_bar_extent),
            top_outer_estimated=bool(getattr(r, "top_outer_estimated", False)),
            bottom_outer_estimated=bool(getattr(r, "bottom_outer_estimated", False)),
            bottom_pushed=float(getattr(r, "bottom_pushed", 0.0) or 0.0),
            vlines_snapped=int(getattr(r, "vlines_snapped", 0) or 0),
            v_outer_side=r.v_outer_side, v_outer_offset=_f(r.v_outer_offset),
            v_outer_estimated=bool(getattr(r, "v_outer_estimated", False)),
            vline_segments=int(r.vline_segments),
            bend_w80_med=_f(r.bend_w80_med), bend_w80_max=_f(r.bend_w80_max),
            vline_filled=[bool(x) for x in (r.vline_filled or [])],
        )

    @model_serializer(mode="wrap")
    def _drop_false_v_outer_estimated(self, handler):
        d = handler(self)
        if isinstance(d, dict) and not d.get("v_outer_estimated"):
            d.pop("v_outer_estimated", None)
        return d

    def to_result(self) -> BorderDetectionResult:
        return BorderDetectionResult(
            width=self.width, height=self.height,
            top=self.top.to_hline(), bottom=self.bottom.to_hline(),
            verticals=[v.to_vline() for v in self.verticals],
            head_raise=[h.to_hr() for h in self.head_raise],
            top_outer_offset=self.top_outer_offset, bottom_outer_offset=self.bottom_outer_offset,
            top_frame_kind=self.top_frame_kind, bottom_frame_kind=self.bottom_frame_kind,
            top_bar_extent=self.top_bar_extent, bottom_bar_extent=self.bottom_bar_extent,
            top_outer_estimated=self.top_outer_estimated,
            bottom_outer_estimated=self.bottom_outer_estimated,
            bottom_pushed=self.bottom_pushed, vlines_snapped=self.vlines_snapped,
            v_outer_side=self.v_outer_side, v_outer_offset=self.v_outer_offset,
            v_outer_estimated=self.v_outer_estimated,
            vline_segments=self.vline_segments,
            vline_filled=list(self.vline_filled),
            bend_w80_med=self.bend_w80_med, bend_w80_max=self.bend_w80_max,
            verticals_straight=[v.to_vline() for v in self.verticals_straight],
        )


def _f(x) -> float | None:
    return None if x is None else float(x)


BORDERS = register_kind(ProductKindSpec(
    id="borders", title="Step1 版框 + 界行", storage="numeric", unit="page",
    schema=Borders, coord_space=RAW_TR))
