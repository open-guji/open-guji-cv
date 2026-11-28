"""第四步 4c「格况」`cell_state` 的产物（2026-11-28，CV4 P3b；设计见 ai-team domain/CV/A24「第四步定字-子步重构设计」4c 一节与 P3b 依赖清单）。

只装**不看放行状态**的格况证据：印章／遮挡、盖章空栏候选、字框几何、墨点／印的格旗、雙行小注分法不均的列旗、题列套语。
这些原来散在 `seed_admit_cell_state`，每个 pass 边判边改格；现在先算成本产物，收尾 `seed_admit` 读它、再按放行状态决定升降。
单独放一个文件，不牵连 `recog.py`。numeric，一页一份。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import COLUMN_PX, ProductKindSpec
from ...core.step import register_kind

#: 格况取值。`blank`（整理本空格位、图上也没墨）本期不出：它要读库判决和放行状态，仍在收尾 `_blank_ink_pass` 里。
CELL_STATES = ("char", "blank", "occluded", "seal", "seg_bad", "non_char")


class CellStateRec(BaseModel):
    id: str
    col: int
    slot: int
    sub: str | None = None
    state: str = "char"
    """`CELL_STATES` 之一。优先级 seal > occluded > seg_bad > non_char > char。"""
    evidence: dict = Field(default_factory=dict)
    """证据，只记看到的：`occluded`{density,default,src}、`seal_blank`{seal_score,overlap}、`seg_box`[判据]、`ink`[ink_seal|ink_speck]、`speck_half`、`ref_blank`。"""


class PageCellState(BaseModel):
    page: int
    cells: list[CellStateRec] = Field(default_factory=list)
    ran: list[str] = Field(default_factory=list)
    """本页真算了的探测器：occluded／seal_blank／seg_box／ink／jiazhu_uneven／header_formula。不在表里＝参数没开，收尾自己现算（或本来就不跑）。"""
    # 以下是收尾各 pass 直接读的探测原值（无损），键类型按 JSON 落盘后读回为准
    occluded: dict[str, list] = Field(default_factory=dict)
    """{字位 id: [密度, 默认字|None, 默认字来源]}——`seed_admit_cell_state._occluded` 的结果。"""
    seal_blank: list[dict] = Field(default_factory=list)
    """`occlusion.page_seal_blank` 的候选格：{col, slot, sub, seal_score, overlap}。"""
    seg_box: dict[str, list[str]] = Field(default_factory=dict)
    ink_flags: dict[str, list[str]] = Field(default_factory=dict)
    """{格 id: 格旗}；只存带 ink_seal／ink_speck 的格（其余格旗收尾不读）。"""
    speck_half: list[str] = Field(default_factory=list)
    jiazhu_uneven: dict[str, list[list[int]]] = Field(default_factory=dict)
    """{列号: [[首格, 末格]…]}。"""
    header_lines: dict[str, str] = Field(default_factory=dict)
    """{列号: 整理本行}。"""

    def by_id(self) -> dict[str, CellStateRec]:
        return {r.id: r for r in self.cells}

    # ── 还原成收尾各 pass 要的原形 ────────────────────────────────
    def occluded_map(self) -> dict[str, tuple[float, str | None, str]]:
        return {k: (float(v[0]), v[1], v[2]) for k, v in self.occluded.items()}

    def seal_blank_map(self) -> dict[tuple[int, int, str], dict]:
        return {(d["col"], d["slot"], d["sub"]): {"seal_score": d["seal_score"], "overlap": d["overlap"]} for d in self.seal_blank}

    def ink_facts(self) -> tuple[dict[str, set[str]], set[str]]:
        return {k: set(v) for k, v in self.ink_flags.items()}, set(self.speck_half)

    def uneven_spans(self) -> dict[int, list[tuple[int, int]]]:
        return {int(k): [(int(a), int(b)) for a, b in v] for k, v in self.jiazhu_uneven.items()}

    def header_line_map(self) -> dict[int, str]:
        return {int(k): v for k, v in self.header_lines.items()}


CELL_STATE = register_kind(ProductKindSpec(
    id="cell_state", title="第四步 4c 格况", storage="numeric", unit="cell",
    schema=PageCellState, coord_space=COLUMN_PX))
