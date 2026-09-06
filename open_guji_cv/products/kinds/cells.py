"""cells：Step3 单列文字切分的产物（numeric）。

坐标在**列图坐标**（COLUMN_PX，左上原点）；`quad_page` 是同一格四角经 Step2
逆映射回原图、再换算到规范空间 raw_page_px@top-right 的结果（没有映射时为 None）。
slot 编号：正文 1..n_body_slots，抬头格 -n_raised..-1，跳过 0；pos 是 1 起的物理位置。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import COLUMN_PX, ProductKindSpec
from ...core.step import register_kind

Point = tuple[float, float]


class CellRec(BaseModel):
    slot: int
    pos: int
    y0: float
    y1: float
    x0: float
    x1: float
    kind: str                      # char | blank | jiazhu_a | jiazhu_b
    sub: str | None = None         # a / b / None
    order: int
    gap_center: float | None = None
    ink_ratio: float = 0.0
    raised: bool = False
    quad_page: list[Point] | None = None   # 原图规范空间四角 [(x,y)…]，右上原点
    seam_top: list[int] | None = None      # 折线缝（列图坐标，每 x 一个 y，从 x0 起）；见 utils/seam.py
    seam_bottom: list[int] | None = None


class ColumnCells(BaseModel):
    col: int
    ok: bool                       # segment_column 有解
    error: str | None = None
    n_body_slots: int
    n_raised: int = 0
    period: float | None = None
    ref_w: float | None = None
    content_x: tuple[float, float] | None = None
    border_top: float | None = None
    border_bottom: float | None = None
    top_slack: float = 0.0
    boundaries: list[float] = Field(default_factory=list)
    cells: list[CellRec] = Field(default_factory=list)


class PageCells(BaseModel):
    page: int
    period: float | None
    ref_w: float | None
    columns: list[ColumnCells]

    def column(self, col: int) -> ColumnCells | None:
        return next((c for c in self.columns if c.col == col), None)


CELLS = register_kind(ProductKindSpec(
    id="cells", title="Step3 字格", storage="numeric", unit="column",
    schema=PageCells, coord_space=COLUMN_PX))
