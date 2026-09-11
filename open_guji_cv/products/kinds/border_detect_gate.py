"""border_detect_gate：Step1 → Step2 交接闸的裁决（numeric，页级）。

与闸2（`gate.py`）、闸3（`row_segment_gate.py`）是各自独立的产物类型——
这道闸记的是 Step1 探测本身够不够格，不是给下游传参数（闸2的 `GateColumn`
带 `content_x`/`border_top` 这类要喂给 Step3 的量，这里没有），字段不同、
不该共用一个 schema。

`admitted` 只由 **block 级**判据决定（L1：列数不对——整页性的问题，
`column_warp` 拿不到正确的列窗口就没法往下走）；**flag 级**判据（L2 界行
w80、L3 版框墨、L4 抬头框）写进 `flags`，不影响 `admitted`——这几条现在
都没有已验证的"超了就该整页作废"的判准，只适合先标出来供人复核
（同 `row_segment_gate.py` 的分法：block 与 flag 是这道闸自己在
`run_page` 里按判据决定的，`GateSpec.on_fail` 只是整道闸的默认处置）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import ProductKindSpec, RAW_TR
from ...core.step import register_kind


class BorderDetectGateManifest(BaseModel):
    page: int
    admitted: bool
    reject: list[str] = Field(default_factory=list)
    """block 级判据命中的原因；非空则 `admitted=False`。"""
    flags: list[str] = Field(default_factory=list)
    """flag 级判据命中的原因；不影响 `admitted`，下游/人按需读取。"""
    n_cols: int
    expected_cols: int
    bend_w80_max: float | None = None
    top_outer_offset: float | None = None
    bottom_outer_offset: float | None = None
    n_head_raise: int = 0


BORDER_DETECT_GATE_MANIFEST = register_kind(ProductKindSpec(
    id="border_detect_gate_manifest", title="Step1→2 交接闸裁决",
    storage="numeric", unit="page",
    schema=BorderDetectGateManifest, coord_space=RAW_TR))
