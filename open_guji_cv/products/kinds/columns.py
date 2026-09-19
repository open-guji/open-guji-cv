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
    case: str          # a / b / c / d / e（见 column_projection.column_border_trim）


class ColumnTriage(BaseModel):
    """这一列清得「拿得准还是拿不准」（2026-09-17，见 utils/column_triage.py）。

    Step2 此前只输出「削了几行」，把**拿得准与拿不准的区别**丢掉了：两种列在
    产物里长得一模一样，人不知道该复核哪些。这里显式记下来，供审阅台按类抽样、
    供闸按类决定拦不拦。

    `side_class`：clean / mixed（没零区，人也标不出唯一坐标）/ eat（已吃进字身）
    `top_class` / `bot_class`：none / clean / glued（框粘字，切不出界）/ idk
    `pad_top` / `pad_bottom`：走峰法给的「该削几行」，**只在 clean 时有意义**；
      其余为 0——拿不准时宁可留残墨也不切字。
    """
    side_class: str
    top_class: str
    bot_class: str
    pad_top: int = 0
    pad_bottom: int = 0


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
    triage: ColumnTriage | None = None   # 老产物没有这一项
    side_floor: float              # 两侧外 25% 最低墨占比（原始矫正图上量）
    stamp_noise: float = 0.0       # 中等面积孤立墨点密度（原始矫正图上量，抓整列噪点污染）
    # 清理**之后**上/下端残留的满宽连续段行数，0 = 削干净了。闸2 `frame_residue`
    # 判据用；见 `steps/column_warp.FRAME_RESIDUE_*` 的标定记录。老产物没有这两项。
    frame_residue_top: int = 0
    frame_residue_bottom: int = 0


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
