"""自由版式管线 `keben_free` 的三种产物（numeric，页级）。坐标一律规范空间 raw_page_px@top-right。

- `layout_blocks`（Step1 `block_detect`）：版框、长线、文字块（自动或人标）；
- `free_columns`（Step2 `column_trace`）：每块的列，左右缝是逐行 x 的折线（按 `step` 行采样）；
- `free_cells`（Step3 `cell_cut`）：字框（页面坐标）＋种类＋读序。

与刻本链 `borders / column_windows / cells` 分开立种类：这里的块可以有好几块、列界是弯缝、
列里大字和双行小注交替，硬塞进那几种会把它们的含义撑坏。要接 Step4 以后的步骤时再写转换。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import RAW_TR, ProductKindSpec
from ...core.step import register_kind

Box = tuple[float, float, float, float]          # x0, y0, x1, y1


class RuleRec(BaseModel):
    orient: str                     # h | v
    a: float                        # 横线：右端（x_tr=0）处 y；竖线：顶端（y=0）处 x_tr
    slope: float                    # 横线 dy/dx_tr；竖线 dx_tr/dy
    lo: float                       # 沿线方向覆盖范围（横线是 x_tr，竖线是 y）
    hi: float
    n_strips: int


class BlockRec(BaseModel):
    index: int                      # 读序，从 1 起
    box: Box
    kind: str = "text"              # text | skip
    source: str = "auto"            # auto | hint
    cols_hint: int | None = None
    vrules: list[float] = Field(default_factory=list)   # 块内竖线 x_tr（块中线高度处）


class LayoutBlocks(BaseModel):
    page: int
    width: int
    height: int
    page_type: str = "body"         # body | skip（人标整页不切）
    hinted: bool = False            # 这页有人标提示
    frame: Box | None = None        # 版框内沿
    frame_found: dict[str, bool] = Field(default_factory=dict)
    rules: list[RuleRec] = Field(default_factory=list)
    blocks: list[BlockRec] = Field(default_factory=list)


class ColumnRec(BaseModel):
    col: int                        # 页内列号（跨块连续，读序），从 1 起
    block: int                      # 属于第几块
    y0: float                       # 列的上下（块的上下）
    y1: float
    step: int                       # 缝的采样行距
    right: list[float]              # 右缝 x_tr，第 i 个是 y0 + i·step 行（最后一个是 y1−1 行）
    left: list[float]               # 左缝 x_tr


class BlockColumnsRec(BaseModel):
    block: int
    n: int
    n_source: str                   # hint | auto | rule
    alt_n: list[int] = Field(default_factory=list)
    pitch: float | None = None
    shear: float = 0.0


class FreeColumns(BaseModel):
    page: int
    width: int
    height: int
    blocks: list[BlockColumnsRec] = Field(default_factory=list)
    columns: list[ColumnRec] = Field(default_factory=list)


class FreeCellRec(BaseModel):
    col: int
    order: int                      # 列内读序，从 1 起
    kind: str                       # char | jiazhu_a（右线）| jiazhu_b（左线）| jiazhu_solo
    zone: int                       # 列内第几区（大字/双行注/单行注交替），从 1 起
    box: Box                        # 页面坐标外接框
    ink: int


class FreeCells(BaseModel):
    page: int
    width: int
    height: int
    n_cells: int = 0
    cells: list[FreeCellRec] = Field(default_factory=list)


LAYOUT_BLOCKS = register_kind(ProductKindSpec(
    id="layout_blocks", title="自由版式 Step1 文字块", storage="numeric", unit="page",
    schema=LayoutBlocks, coord_space=RAW_TR))
FREE_COLUMNS = register_kind(ProductKindSpec(
    id="free_columns", title="自由版式 Step2 列（弯缝）", storage="numeric", unit="page",
    schema=FreeColumns, coord_space=RAW_TR))
FREE_CELLS = register_kind(ProductKindSpec(
    id="free_cells", title="自由版式 Step3 字框", storage="numeric", unit="page",
    schema=FreeCells, coord_space=RAW_TR))
