"""char_index（numeric）+ char_patch（image_cache）：Step4 字框收缩的产物。

`bbox_col` 在列图坐标；`bbox_page` 是同一框回到原图、换到规范空间 raw_page_px@top-right
的外接框。图块 PNG 走缓存，key = p{page}c{col}s{slot}[a|b]。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import COLUMN_PX, RAW_TR, ProductKindSpec
from ...core.step import register_kind


class CharRec(BaseModel):
    id: str                                # book:page:col:idx[a|b]（沿用 CharInstance.id 口径）
    slot: int
    pos: int
    idx: int                               # 喂给 CharExtractor 的 0 起格号（= pos - 1）
    sub: str | None = None
    cell_type: str                         # char | empty（CharExtractor 的判定）
    step3_kind: str = "char"               # Step3 的判定：char | jiazhu | blank
    bbox_col: tuple[float, float, float, float]
    bbox_page: tuple[float, float, float, float] | None = None
    ink_ratio: float = 0.0
    height: float = 0.0
    width: float = 0.0
    flags: list[str] = Field(default_factory=list)
    patch_key: str | None = None           # 缓存里的键；empty 格没有图块


class ColumnChars(BaseModel):
    col: int
    ok: bool
    error: str | None = None
    n_instances: int = 0
    chars: list[CharRec] = Field(default_factory=list)


class PageChars(BaseModel):
    page: int
    columns: list[ColumnChars]

    def column(self, col: int) -> ColumnChars | None:
        return next((c for c in self.columns if c.col == col), None)


CHAR_INDEX = register_kind(ProductKindSpec(
    id="char_index", title="Step4 字框（紧框 + flags）", storage="numeric", unit="cell",
    schema=PageChars, coord_space=COLUMN_PX))

CHAR_PATCH = register_kind(ProductKindSpec(
    id="char_patch", title="字块图（缓存）", storage="image_cache", unit="cell",
    coord_space=COLUMN_PX, ext="png"))
