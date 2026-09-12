"""char_index（numeric）+ char_patch（image_cache）：Step4 字框收缩的产物。

`bbox_col` 在列图坐标；`bbox_page` 是同一框回到原图、换到规范空间 raw_page_px@top-right
的外接框。图块 PNG 走缓存，key = p{page}c{col}s{slot}[a|b]。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import COLUMN_PX, RAW_TR, ProductKindSpec
from ...core.step import register_kind


class CandidatePatch(BaseModel):
    """多候选切点旁字位的**一个候选**试切字块（Step4）。

    只在这个格位邻接的切点是**多候选**（`CutPointCandidates.candidates` ≥2）
    时才生成——单一候选（算法有把握）不多切、不多存，成本只落在真正
    要下游判断的地方。

    一个格位最多邻接两条候选切点（`side="above"` 是它跟上一格之间那条，
    `side="below"` 是它跟下一格之间那条），两侧各自独立试、不做笛卡尔积
    （两个切点是独立决策，没有"上邻选A且下邻选B"这种耦合判据）——所以
    `(side, cand_idx)` 才是这一组变体里的唯一键，`cand_idx` 单独并不唯一
    （同一格两侧都可能各有一个 `cand_idx=0` 的 straight 候选）。`cand_idx`
    对应该侧那条 `CutPointCandidates.candidates` 的下标，与
    `glyph_match.MatchRec.cand_variants` 按 `(side, cand_idx)` 配对。
    """
    side: str                              # above | below：这个候选来自哪一侧的切点
    cand_idx: int                          # 对应那一侧 CutPointCandidates.candidates 下标
    kind: str                              # straight | seam_narrow | seam_wide
    patch_key: str                         # 缓存里的键，见 core.spec.cell_key 变体
    bbox_col: tuple[float, float, float, float]


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
    cand_variants: list[CandidatePatch] = Field(default_factory=list)
    """这个格位邻接的多候选切点，每候选一份试切字块；空列表 = 两侧都是单一
    候选（不需要人裁决），`bbox_col`/`patch_key` 就是唯一答案，下游忽略此
    字段完全不受影响（向后兼容）。"""


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
