"""第四步出口 gate `decide_gate` 的产物（2026-11-28，CV4；设计见 ai-team domain/CV/A24「第四步定字-子步重构设计」第三节）。

gate **只检测、不判断**（Sheldon 11-28 定）：读第四步全部产物，出检测清单；不改任何格的字、不改放行、不进任何
格的放行判断。单独放一个文件，不牵连 `recog.py`／`decide.py`。numeric，一页一份。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import COLUMN_PX, ProductKindSpec
from ...core.step import register_kind


class GateCheck(BaseModel):
    """一条检测结果：只描述「看到了什么」。"""
    name: str                       # 检测项名（英文 2–3 词）：ref_shift、char_not_in_evidence…
    level: str                      # fail：大概率有错，要人或书 Project 处理｜flag：可疑，留证据攒阈值
    unit: str                       # page｜col｜cell
    key: str                        # page：页号；col：列号；cell：格 id
    reason: str                     # 人读的一句话
    metrics: dict = Field(default_factory=dict)


class PageDecideGate(BaseModel):
    page: int
    passed: bool = True             # 没有 fail 级检测项
    checks: list[GateCheck] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    """n_cells、n_admit、admit_rate、哪些上游缺席（`missing`）。"""

    def fails(self) -> list[GateCheck]:
        return [c for c in self.checks if c.level == "fail"]


DECIDE_GATE = register_kind(ProductKindSpec(
    id="decide_gate", title="第四步出口 gate 检测结果", storage="numeric", unit="page",
    schema=PageDecideGate, coord_space=COLUMN_PX))
