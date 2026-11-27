"""第三步识字的新产物（2026-11-27，Sheldon 11-26 定的第三步重构）：3b `glyph_near`、收尾 `glyph_analyzer`。

设计见 ai-team 《第三步识字重构设计》（https://claude.ai/artifact/EdSn56RuC1viVHFpafy5Fz）：
- 3a `glyph_match` 出候选与相似度；
- 3b `glyph_near` 只处理触发了形近字组的格，按组登记的方法给组内每个字一个新的分（`sims`）＋证据，不定字；
- 收尾 `glyph_analyzer` 把各小步汇总成 `cands`（字＋p＋证据）与 `p_map`（切断、混边框等其他特征的概率），
  第三步不判断放不放行，第四步只读这里的 p。

单独放一个文件（不写进 `recog.py`）：`recog.py` 是现役几步的产物定义，动它会牵连那几步。都是 numeric。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import COLUMN_PX, ProductKindSpec
from ...core.step import register_kind


class NearMethodOut(BaseModel):
    """3b 一个方法对一格的输出：组内各字的分（这个方法自己的尺度，未校准），外加证据。"""
    method: str                                   # 「方法:组」，如 cnn_small:gong
    sims: dict[str, float] = Field(default_factory=dict)
    evidence: dict = Field(default_factory=dict)


class NearRec(BaseModel):
    id: str
    slot: int
    sub: str | None = None
    group: str                                    # 触发的字组 id
    trigger: str = ""                             # 怎么触发的：member（首位在组里）／close（组内两字分差在 δ 内）
    methods: list[NearMethodOut] = Field(default_factory=list)


class ColumnNear(BaseModel):
    col: int
    chars: list[NearRec] = Field(default_factory=list)


class PageNear(BaseModel):
    page: int
    #: 各组各方法的模型目录指纹（`GlyphNearParams.methods_sha`）。写进产物，换校准表时 sims 不变、产物 sha 也会变，
    #: 收尾 `glyph_analyzer` 跟着过期
    methods_sha: str = ""
    columns: list[ColumnNear] = Field(default_factory=list)

    def by_id(self) -> dict[str, NearRec]:
        return {r.id: r for c in self.columns for r in c.chars}


class CandRec(BaseModel):
    """3c 一格的按图候选：[字, 余弦]，已按分降序；`fam_of` 记哪些字是按异体族并进来的（并进来的字→它所属的头名字）。"""
    id: str
    slot: int
    sub: str | None = None
    ran: bool = True
    cands: list[list] = Field(default_factory=list)        # [[字, 分], …]，最多 topk 个
    fam_of: dict[str, str] = Field(default_factory=dict)


class ColumnCand(BaseModel):
    col: int
    chars: list[CandRec] = Field(default_factory=list)


class PageCand(BaseModel):
    page: int
    #: 向量模型与字表包的版本，如 "r5@d2ce8bab+emb-807344bd"；写进产物，换模型或换字表包本步与收尾就过期
    model: str = ""
    columns: list[ColumnCand] = Field(default_factory=list)

    def by_id(self) -> dict[str, CandRec]:
        return {r.id: r for c in self.columns for r in c.chars}


class FinalCand(BaseModel):
    """收尾的一个候选：字、校准后的 p（还没有校准来源的为 None）、各小步的证据（a／b／c 键）。"""
    char: str
    p: float | None = None
    evidence: dict = Field(default_factory=dict)


class FinalRec(BaseModel):
    id: str
    slot: int
    sub: str | None = None
    cands: list[FinalCand] = Field(default_factory=list)
    #: 其他特征的概率：cut（字被切断）、border（混入边框）、residue（混入上下字残留）、stain（背景污染）…
    #: 只放有校准来源的键，没有就不写；以后加键不改格式。
    p_map: dict[str, float] = Field(default_factory=dict)
    #: p 从哪来，如 "near:cnn_small:gong"；没有任何校准来源时为空串
    p_src: str = ""


class ColumnFinal(BaseModel):
    col: int
    chars: list[FinalRec] = Field(default_factory=list)


class PageFinal(BaseModel):
    page: int
    model: str = ""                               # 收尾口径版本，如 glyph-analyzer/0
    columns: list[ColumnFinal] = Field(default_factory=list)

    def by_id(self) -> dict[str, FinalRec]:
        return {r.id: r for c in self.columns for r in c.chars}


GLYPH_CANDIDATE = register_kind(ProductKindSpec(
    id="glyph_candidate", title="3c 按图候选", storage="numeric", unit="cell",
    schema=PageCand, coord_space=COLUMN_PX))

GLYPH_NEAR = register_kind(ProductKindSpec(
    id="glyph_near", title="3b 形近字组分析", storage="numeric", unit="cell",
    schema=PageNear, coord_space=COLUMN_PX))

GLYPH_ANALYZER = register_kind(ProductKindSpec(
    id="glyph_analyzer", title="3 识字收尾（汇总）", storage="numeric", unit="cell",
    schema=PageFinal, coord_space=COLUMN_PX))
