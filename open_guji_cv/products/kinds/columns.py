"""Step2 的产物：column_windows（numeric）+ column_raw / column_image（image_cache）。

numeric 里存的是复现列图所需的全部量（边线含折点、窗口上下界、版框在列图里的 y、
文字带、版框修剪档、side_floor）；列图本身只进缓存，缺了由 Step2 现算。
对齐 scripts/regen_step2_columns.py 的 windows.json + export_step3_input 的列级字段。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import COLUMN_PX, RAW_TR, ProductKindSpec
from ...core.step import register_kind
from .borders import VLineRec


class BorderTrim(BaseModel):
    px: int
    case: str          # a / b / c / d


class ColumnWindowRec(BaseModel):
    col: int                       # 右→左，从 1
    left_line: VLineRec
    right_line: VLineRec
    top_y: float                   # 矫正窗口上界（规范空间 y）
    bottom_y: float
    border_top_y: float            # 主上版框在该列的 y
    border_bottom_y: float
    border_top_in_column: float    # = border_top_y - top_y（列图坐标）
    border_bottom_in_column: float
    raised: bool = False
    head_raise_inner_y: float | None = None
    warped_size: tuple[int, int]   # (w, h) —— 以实际列图 shape 为准（三段页可能差 1~2px）
    band: tuple[int, int]          # 文字带 [x_lo, x_hi)，列图坐标
    trim_top: BorderTrim
    trim_bottom: BorderTrim
    side_floor: float              # 两侧外 25% 最低墨占比（原始矫正图上量）


class PageWindows(BaseModel):
    page: int
    page_size: tuple[int, int]     # (w, h)
    vline_segments: int = 1
    denoised: bool = True
    columns: list[ColumnWindowRec] = Field(default_factory=list)

    def column(self, col: int) -> ColumnWindowRec | None:
        return next((c for c in self.columns if c.col == col), None)


COLUMN_WINDOWS = register_kind(ProductKindSpec(
    id="column_windows", title="Step2 逐列窗口 / warp 参数 / 文字带", storage="numeric",
    unit="column", schema=PageWindows, coord_space=RAW_TR))

COLUMN_RAW = register_kind(ProductKindSpec(
    id="column_raw", title="矫正 + 去噪列图（缓存）", storage="image_cache", unit="column",
    coord_space=COLUMN_PX))

COLUMN_IMAGE = register_kind(ProductKindSpec(
    id="column_image", title="清理后列图（缓存）", storage="image_cache", unit="column",
    coord_space=COLUMN_PX))
