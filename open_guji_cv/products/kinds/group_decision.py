"""第四步 4d「字组」`group_decision` 的产物（2026-11-28，CV4 P3c；设计见 ai-team domain/CV/A24「第四步定字-子步重构设计」4d 一节与 P3c 依赖清单）。

**只出原料，不出决定**：字组入口归属、3b 看图判法的原样结论（`glyph_near` 搬来的快照）、按组的字框宽高比证据。
不含补放／改字／降审，也不含文意各层、裁定缓存、`vis_ruling`——这些读邻格放行状态（窗口键），只能在收尾做。
收尾 `seed_admit`（`char_decide`）可选读它：有且 `ran` 里有就用，没有照旧现算（逐格相同）。numeric，一页一份。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import COLUMN_PX, ProductKindSpec
from ...core.step import register_kind

#: 3b 方法里键是「(格 id, 对里两字)」的（一个模型挂多对）与键是「(格 id, 方法指纹)」的；其余键是格 id。
PAIR_KEYED = frozenset({"part_shape"})
MODEL_KEYED = frozenset({"pair_shape", "book_knn", "near_knn", "stroke_veto"})


class GroupDecisionRec(BaseModel):
    id: str
    col: int
    slot: int
    sub: str | None = None
    lift: list[str] | None = None
    """字组入口归属（**待审口径**：假定这格没放行、不是人裁）：`[组 id, "lift"|"joint"]`；落不进任何组 → None。
    已放行格的复核入口（`review`）读最终放行字，不在这里。本版只出不读，收尾仍自己算。"""
    aspect: dict[str, float] = Field(default_factory=dict)
    """按组的字框宽高比证据 `{组 id: 宽/高}`（只给有宽高比判法的组，现 ry 日曰，且在书的 `fold_groups` 里）。只是证据，窄宽判与门槛在收尾。"""


class PageGroupDecision(BaseModel):
    page: int
    cells: list[GroupDecisionRec] = Field(default_factory=list)
    ran: list[str] = Field(default_factory=list)
    """本页真算了的原料：`entry`（入口归属）、`wh`（字框宽高，fold 宽高比用）、`near:<方法>`（3b 看图判法快照，每个方法一项）。
    不在表里＝参数没开，收尾自己现算。"""
    wh: dict[str, list[float]] = Field(default_factory=dict)
    """{格 id: [宽, 高]}（`char_index`，收尾 `fold_aspect` 直接读；逐格同 `_fold_pass(wh=…)`）。"""
    near: dict[str, list[dict]] = Field(default_factory=dict)
    """3b 看图判法的原样结论快照 `{方法: [{k: 键, ev: 证据}…]}`，键与 `seed_admit_shapes._near_from_3b／_near_by_model_from_3b` 同形：
    普通方法 `[格 id]`；part_shape `[格 id, [字, 字]]`；pair_shape／book_knn／near_knn／stroke_veto `[格 id, 模型指纹]`。"""
    handling: dict[str, dict] = Field(default_factory=dict)
    """按组的处理方式（登记表 `handling`：看图方法、文意、门槛、放行或只出证据）。本页所在书的定稿快照（`GroupDecisionParams.resolved`，登记表缺省＋书级覆盖）。**本版只记、收尾不读**。"""

    def by_id(self) -> dict[str, GroupDecisionRec]:
        return {r.id: r for r in self.cells}

    def wh_map(self) -> dict[str, tuple]:
        return {k: (v[0], v[1]) for k, v in self.wh.items()}

    def near_map(self, method: str) -> dict:
        """还原成 `_near_from_3b`／`_near_by_model_from_3b` 返回的字典形状。"""
        out: dict = {}
        for it in self.near.get(method, []):
            k = it["k"]
            if method in PAIR_KEYED:
                key = (k[0], tuple(k[1]))
            elif method in MODEL_KEYED:
                key = (k[0], k[1])
            else:
                key = k[0]
            out[key] = it["ev"]
        return out


def pack_near(method: str, got: dict) -> list[dict]:
    """`near_map` 的反向：把读 3b 得到的字典存成 JSON 友好的列表（保持原字典顺序）。"""
    out = []
    for key, ev in got.items():
        if method in PAIR_KEYED:
            k = [key[0], list(key[1])]
        elif method in MODEL_KEYED:
            k = [key[0], key[1]]
        else:
            k = [key]
        out.append({"k": k, "ev": ev})
    return out


GROUP_DECISION = register_kind(ProductKindSpec(
    id="group_decision", title="第四步 4d 字组原料", storage="numeric", unit="cell",
    schema=PageGroupDecision, coord_space=COLUMN_PX))
