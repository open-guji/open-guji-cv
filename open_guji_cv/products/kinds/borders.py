"""borders：Step1 边框探测的产物（numeric）。

镜像 `utils/border_geometry.BorderDetectionResult`——它本身就用右上原点（x 向左、
列从右起），所以这里的坐标空间就是规范空间 raw_page_px@top-right，不换算。
`BorderDetectionResult` 没有序列化方法，双向转换在这里。
**折线的 k2/k3/y1/y2 必须一起存**，否则三段页退化成第一段外推的直线且无法还原。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import RAW_TR, ProductKindSpec
from ...core.step import register_kind
from ...utils.border_geometry import (BorderDetectionResult, HeadRaiseBorder, HLine,
                                      VLine)


class HLineRec(BaseModel):
    y_at_right: float
    slope: float
    kind: str

    @classmethod
    def of(cls, h: HLine) -> "HLineRec":
        return cls(y_at_right=float(h.y_at_right), slope=float(h.slope), kind=h.kind)

    def to_hline(self) -> HLine:
        return HLine(y_at_right=self.y_at_right, slope=self.slope, kind=self.kind)


class VLineRec(BaseModel):
    x_at_top: float
    slope: float
    k2: float | None = None
    k3: float | None = None
    y1: float | None = None
    y2: float | None = None
    segments: int = 1

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
    col: int
    inner_y: float
    outer_y: float
    estimated: bool = False

    @classmethod
    def of(cls, h: HeadRaiseBorder) -> "HeadRaiseRec":
        return cls(col=int(h.col), inner_y=float(h.inner_y), outer_y=float(h.outer_y),
                   estimated=bool(h.estimated))

    def to_hr(self) -> HeadRaiseBorder:
        return HeadRaiseBorder(col=self.col, inner_y=self.inner_y, outer_y=self.outer_y,
                               estimated=self.estimated)


class Borders(BaseModel):
    width: int
    height: int
    expected_cols: int
    top: HLineRec
    bottom: HLineRec
    verticals: list[VLineRec]                    # 右→左，N+1 条
    verticals_straight: list[VLineRec] = Field(default_factory=list)   # 折线拟合前的直线
    head_raise: list[HeadRaiseRec] = Field(default_factory=list)
    top_outer_offset: float | None = None
    bottom_outer_offset: float | None = None
    v_outer_side: str | None = None
    v_outer_offset: float | None = None
    vline_segments: int = 1
    bend_w80_med: float | None = None
    bend_w80_max: float | None = None

    @classmethod
    def from_result(cls, r: BorderDetectionResult, expected_cols: int) -> "Borders":
        return cls(
            width=int(r.width), height=int(r.height), expected_cols=int(expected_cols),
            top=HLineRec.of(r.top), bottom=HLineRec.of(r.bottom),
            verticals=[VLineRec.of(v) for v in r.verticals],
            verticals_straight=[VLineRec.of(v) for v in (r.verticals_straight or [])],
            head_raise=[HeadRaiseRec.of(h) for h in (r.head_raise or [])],
            top_outer_offset=_f(r.top_outer_offset), bottom_outer_offset=_f(r.bottom_outer_offset),
            v_outer_side=r.v_outer_side, v_outer_offset=_f(r.v_outer_offset),
            vline_segments=int(r.vline_segments),
            bend_w80_med=_f(r.bend_w80_med), bend_w80_max=_f(r.bend_w80_max),
        )

    def to_result(self) -> BorderDetectionResult:
        return BorderDetectionResult(
            width=self.width, height=self.height,
            top=self.top.to_hline(), bottom=self.bottom.to_hline(),
            verticals=[v.to_vline() for v in self.verticals],
            head_raise=[h.to_hr() for h in self.head_raise],
            top_outer_offset=self.top_outer_offset, bottom_outer_offset=self.bottom_outer_offset,
            v_outer_side=self.v_outer_side, v_outer_offset=self.v_outer_offset,
            vline_segments=self.vline_segments,
            bend_w80_med=self.bend_w80_med, bend_w80_max=self.bend_w80_max,
            verticals_straight=[v.to_vline() for v in self.verticals_straight],
        )


def _f(x) -> float | None:
    return None if x is None else float(x)


BORDERS = register_kind(ProductKindSpec(
    id="borders", title="Step1 版框 + 界行", storage="numeric", unit="page",
    schema=Borders, coord_space=RAW_TR))
