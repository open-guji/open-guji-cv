"""Step6b `group_decide` 的产物：形近字组分类器的逐格答案（overview GUJI-49，Step6b PR1）。

只是**证据**，不是放行判决：`action` 在 PR1 恒为 `none`，抬升／降级留给 Step7（PR2）。
字段口径见 overview `项目进展/CV形近字分组/计划/Step6b-PR1-实现说明-Evan.md` §三。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import COLUMN_PX, ProductKindSpec
from ...core.step import register_kind


class GroupDecRec(BaseModel):
    id: str                                  # book:page:col:slot，同 glyph_match 的字位 id
    group: str                               # 字组 id（ry／jys）
    ref: str                                 # 整理本对位字——判「属于哪组」的依据
    char: str | None = None                  # 分类器给的字；弃权＝None
    conf: float | None = None                # 表路（多遍一致）可为 None
    why: str = ""                            # cache_miss／ctx_mismatch／ver_mismatch／表里自带的原因
    action: str = "none"                     # lift|demote|none；PR1 恒 none


class PageGroupDecision(BaseModel):
    page: int
    tables_fingerprint: str = ""             # 判决用的是哪组答案表（内容哈希）
    cells: list[GroupDecRec] = Field(default_factory=list)


GROUP_DECISION = register_kind(ProductKindSpec(
    id="group_decision", title="Step6b 形近字组分类", storage="numeric", unit="cell",
    schema=PageGroupDecision, coord_space=COLUMN_PX))
