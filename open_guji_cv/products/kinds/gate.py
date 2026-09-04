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
    n_raised_hint: int = 0
    """这一列比版式常量**多出来**的字位数（2026-09-03 加）。

    `n_raised` 原先只有页级参数一个来源，可「抬头多一个字」是**逐列**的
    ——同一页上有的抬头列多一格、有的只是整体上挪（vol01/33 四个抬头列
    实测 3 个多一字、1 个不多）。给不出逐列值时 DP 只能在 21 格里硬塞
    22 个字，唯一可行解就是**丢掉首字**：实测 vol01/26c6、33c7/c8、
    47c6/c9、vol02/3c3~c5 这 8 列的墨跨度 / period 是 21.4~22.2，
    首字整个落在首格之上。

    判据是**墨跨度**（首墨到末墨）÷ period，不是「顶端有没有墨」——后者
    分不开「顶格写」和「多一个字」。Step3 用 `n_raised = max(页级参数,
    本列 hint)`，所以给 0 就是不动。
    """
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
