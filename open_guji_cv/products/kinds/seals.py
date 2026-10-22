"""seals：Step0 印章定位（numeric，页级）。印章系统化第 1 期（2026-10-22）。

用户 10-22：印章要在整页识别一开始就定位好，后面各步只读这份结果、不再各自去认。
每页一份，列出本页每一方印：类别、外框、分数、来源。没有印的页 `seals` 为空表。

两类印（殿本四库总目十册普查，设计见 `steps/seal_detect.py` 模块头）：
- `stain` 大印：卷首叶、卷端页的藏书印，斑驳，满是中等墨点，不用识别，只要知道范围；
- `crisp` 小印：卷末「乾隆御覽之寶」，笔画清楚，容易被当成字，覆盖区＝模板笔画。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ...core.spec import ProductKindSpec, RAW_TR
from ...core.step import register_kind


class Seal(BaseModel):
    kind: Literal["stain", "crisp"]
    bbox: tuple[float, float, float, float]
    """外框 [x0, y0, x1, y1]，规范空间（右上原点，x 向左）。"""
    score: float
    """`stain` 是峰值密度（每格中等墨点数）；`crisp` 是模板笔画覆盖率减底色墨率。"""
    source: Literal["density", "template", "manual"]
    template: str = ""
    """`crisp` 命中的模板文件名（`config/seal_templates/`），下游据此复原笔画覆盖区。"""


class PageSeals(BaseModel):
    page: int
    width: int
    height: int
    seals: list[Seal] = Field(default_factory=list)


SEALS = register_kind(ProductKindSpec(
    id="seals", title="Step0 印章定位", storage="numeric", unit="page",
    schema=PageSeals, coord_space=RAW_TR))
