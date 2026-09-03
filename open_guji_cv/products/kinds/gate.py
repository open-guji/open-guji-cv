"""gate_manifest：Step2 → Step3 交接闸的裁决（numeric，页级 + 列级）。

对齐 scripts/export_step3_input.py 的 manifest.json：页级 period / ref_w 用**全部列**算，
列级 content_x / border_top / border_bottom / top_slack 随图传。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import COLUMN_PX, ProductKindSpec
from ...core.step import register_kind


class GateColumn(BaseModel):
    col: int
    admitted: bool
    reject: list[str] = Field(default_factory=list)
    tier: str = "gate"                      # gate | gold
    content_x: tuple[float, float]          # 列图坐标里的文字带 [x_lo, x_hi)
    border_top: float
    border_bottom: float
    top_slack: float = 0.0
    raised: bool = False
    head_raise_inner_y: float | None = None
    warped_size: tuple[int, int]            # (w, h)
    side_floor: float | None = None
    band_width: float


class GateManifest(BaseModel):
    page: int
    admitted: bool                          # L1 页级
    reject: list[str] = Field(default_factory=list)
    period: float | None                    # 页级纵向字距（全部列算）
    ref_w: float | None                     # 页级列距中位数（全部列算）
    column_widths: list[float]
    median_width: float | None
    columns: list[GateColumn]
    contract: list[str] = Field(default_factory=list)

    def admitted_columns(self) -> list[GateColumn]:
        return [c for c in self.columns if c.admitted] if self.admitted else []


GATE_MANIFEST = register_kind(ProductKindSpec(
    id="gate_manifest", title="Step2→3 交接闸裁决", storage="numeric", unit="column",
    schema=GateManifest, coord_space=COLUMN_PX))
