"""row_segment_gate：Step3 → Step4 交接闸的裁决（numeric，页级 + 列级）。

与 `gate.py`（闸2，Step2→3）是两道独立的闸、各自的产物类型——闸2记的是列图
几何量（content_x/border_top…），闸3记的是切分结果本身够不够格，字段不同、
不该共用一个 schema。

`admitted` 只由 **block 级**判据决定（L1：DP 无解 / 格数偏离版式过多）；
**flag 级**判据（L2：R2 可改善格线、R2s 真粘连格线）写进 `flags`，不影响
`admitted`——`GateSpec.on_fail` 是整道闸单一的处置策略，分不出「同一道闸
里这条 block 那条 flag」，这道闸自己在 `run_page` 里按判据分别决定写
`reject`（block）还是 `flags`（flag），下游（Step4）读 `admitted` 决定收不收，
读 `flags` 决定要不要额外注意。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import COLUMN_PX, ProductKindSpec
from ...core.step import register_kind


class RowSegmentGateColumn(BaseModel):
    col: int
    admitted: bool
    reject: list[str] = Field(default_factory=list)
    """block 级判据命中的原因；非空则 `admitted=False`。"""
    flags: list[str] = Field(default_factory=list)
    """flag 级判据命中的原因；不影响 `admitted`，下游按需读取。"""
    n_body_slots: int | None = None
    n_r2: int = 0
    """本列 R2（可改善）格线数。"""
    n_r2s: int = 0
    """本列 R2s（真粘连）格线数。"""
    n_r2x: int = 0
    """本列 R2x（错切）格线数。"""
    sliver_slots: list[int] = Field(default_factory=list)
    """L4（2026-09-18）：本列里**高度远小于一格**的碎格的 slot 号。

    DP 在凑格数时会造出十几像素的碎格（`row_boundaries.BLANK_MIN_RATIO` 注释
    记过这个病：碎格让后面每一格往上挤，累积成相位错位，而**列格数是对的，
    字数对账查不出来**）。这是**格子级**判据，闸3 此前只有页级/列级两层。

    实测 bxgb 全书 20446 格只命中 16 个、集中在 8 列（全在 p53），出卡量可控。
    判据是几何上确定可见的那一类（档 A）——不碰已证否的格高比值与切点局部墨量，
    那两条对「腰斩」两个方向都不可靠，见《计划书》§3.1 的三条负结果。"""


class RowSegmentGateManifest(BaseModel):
    page: int
    admitted: bool
    reject: list[str] = Field(default_factory=list)
    columns: list[RowSegmentGateColumn] = Field(default_factory=list)
    unsupported_layout: bool = False
    """这页是否「版式未支持」（职名/目录类：每列字数非版式格数且逐列不同）。

    **判定落盘、不在前端算**——前端从 `reject` 文本里 startswith 前缀分桶只是
    显示层的事，谁要复核判据得能直接读这个字段与 `n_unsupported_columns`，
    不必去解析中文句子。判据见 `clustering/page_type.py`。
    """
    n_unsupported_columns: int = 0
    """本页「弹性 DP 无解」的列数（判据的原始计数，供复核）。"""

    def admitted_columns(self) -> list[RowSegmentGateColumn]:
        return [c for c in self.columns if c.admitted] if self.admitted else []


ROW_SEGMENT_GATE_MANIFEST = register_kind(ProductKindSpec(
    id="row_segment_gate_manifest", title="Step3→4 交接闸裁决",
    storage="numeric", unit="column",
    schema=RowSegmentGateManifest, coord_space=COLUMN_PX))
