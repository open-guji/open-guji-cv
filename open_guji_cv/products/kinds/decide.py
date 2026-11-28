"""第四步定字的新产物（2026-11-27，候选字线）：4b `context_rank` 的按上下文排序结果。

单独放一个文件（不写进 `recog.py`）：`recog.py` 是现役几步的产物定义，动它会牵连那几步。numeric。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import COLUMN_PX, ProductKindSpec
from ...core.step import register_kind


class CtxRec(BaseModel):
    """4b 一格的结果。`ranked`：[[字, 融合分, 图像分, 填空 logp]…]，按融合分降序；
    `ran` 为假＝没排（池里不足 2 个字、或这格 3a 已判 same 不用排、或填空模型读不出）。"""
    id: str
    slot: int
    sub: str | None = None
    ran: bool = True
    why: str = ""
    ranked: list[list] = Field(default_factory=list)


class ColumnCtx(BaseModel):
    col: int
    chars: list[CtxRec] = Field(default_factory=list)


class PageCtx(BaseModel):
    page: int
    #: 填空模型与融合权重，如 "siku@bb25260d/w0.005"；换了本步与下游就过期
    model: str = ""
    columns: list[ColumnCtx] = Field(default_factory=list)

    def by_id(self) -> dict[str, CtxRec]:
        return {r.id: r for c in self.columns for r in c.chars}


CONTEXT_RANK = register_kind(ProductKindSpec(
    id="context_rank", title="按上下文排序（候选）", storage="numeric", unit="cell",
    schema=PageCtx, coord_space=COLUMN_PX))
