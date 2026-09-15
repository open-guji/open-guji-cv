"""line_index：现代印刷链 Step1（`line_detect`）的产物（numeric，页级）。

与 `borders` 并列产出：`borders` 只装正文列的虚拟界行（给 Step2 算窗口），
这里记**页上探到的全部列**及其类型——脚注列、书口小字列、并列/粘连的宽列——
供闸1 判定、控制台展示与 Step9 排除非正文。坐标是规范空间 raw_page_px@top-right。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import RAW_TR, ProductKindSpec
from ...core.step import register_kind


class LineRec(BaseModel):
    col: int | None                  # 列位号（body / empty，右→左从 1）；其他 None
    kind: str                        # body | empty（空列位）| footnote | margin | wide | noise
    x0: float                        # 规范空间 [x0, x1]（右上原点，x 向左）
    x1: float
    y0: float
    y1: float
    width: float                     # 列墨宽 px
    flags: list[str] = Field(default_factory=list)


class LineIndex(BaseModel):
    page: int
    width: int
    height: int
    em: float | None                 # 字身宽估计（正文列墨宽中位）
    pitch: float | None              # 相邻正文列中心距中位
    n_body: int                      # 有字的正文列数（不含 empty 空列位）
    block: tuple[float, float, float, float] | None = None   # 正文块 (x0, y0, x1, y1)，规范空间
    rules_v: list[tuple[float, float]] = Field(default_factory=list)   # 长竖线 x 段（规范空间）
    rules_h: list[tuple[float, float]] = Field(default_factory=list)   # 长横线 y 段
    lines: list[LineRec] = Field(default_factory=list)


LINE_INDEX = register_kind(ProductKindSpec(
    id="line_index", title="Step1 行（列）探测明细", storage="numeric", unit="page",
    schema=LineIndex, coord_space=RAW_TR))
