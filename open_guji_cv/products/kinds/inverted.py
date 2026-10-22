"""inverted：反色带候选（numeric，页级，Step0）。2026-10-22。

扫描故障让一条横带黑白翻转（纸成黑、字成白），Step1 在带里量不到版框、抬头，字也认不出。
`invert_detect` 每页自动找疑似反色带，列成候选；**候选不自动修**——外框粗线和窄反色带长得几乎
一样，误修把版框翻白会整页切坏（Sheldon 10-22 定「自动认＋送审，人点头才修」）。人点头的页
再按 `rule` 修（同书 yaml `preclean:` 的一条规则）。

坐标是原图像素、左上原点（同 `preclean:` 规则），不是规范空间。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import ProductKindSpec, RAW_TL
from ...core.step import register_kind


class InvertedBand(BaseModel):
    bbox: tuple[int, int, int, int]
    """黑条外接框 [x0, y0, x1, y1]，原图像素、左上原点，闭区间。"""
    flipped_rules: int
    """黑条里变白、带外接着是黑界行的白缝道数（判据见 `steps/invert_detect.py`）。"""
    ink: float
    """外接框里的墨占比（翻转前）。"""
    rule: dict = Field(default_factory=dict)
    """建议的修法：一条 `preclean:` 规则（`kind: inverted_band`，横向一段、上下沿逐列量），人点头后照它修。"""


class PageInverted(BaseModel):
    page: int
    width: int
    height: int
    bands: list[InvertedBand] = Field(default_factory=list)


INVERTED = register_kind(ProductKindSpec(
    id="inverted", title="反色带候选", storage="numeric", unit="page",
    schema=PageInverted, coord_space=RAW_TL))
