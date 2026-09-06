"""Step5 识别层的产物：`glyph_match`（库匹配）与 `ocr_candidates`（OCR 候选）。

两者都是 **numeric**：逐字位存判决与候选，图块本身仍在 `char_patch` 缓存里。
归一图（64×64 {0,1}）不单独立产物——它是 `normalize_patch` 的确定性输出，
现算只要几毫秒，存了反而多一份要失效的东西（设计 §3.8「数值长期、图像即算」）。

## 为什么 `glyph_match` 的指纹要带库指纹

`GlyphMatcher` 查的是 `output/glyph.db`，那是**外部可变状态**：库长大了、
某个条目改判了，同一张图块的判决就会变，而 Step 的代码、参数、上游产物
一个都没动。指纹里不带它，产物就永远显示 fresh、拿着过期判决往下走。
所以 `GlyphMatchStep` 把库的 `(mtime, size, 条目数)` 摘进参数，见那一步的
`db_fingerprint()`。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import COLUMN_PX, ProductKindSpec
from ...core.step import register_kind


class MatchRec(BaseModel):
    """一个字位对库的匹配判决（沿用 `clustering.match.MatchResult` 的语义）。"""
    id: str                                  # book:page:col:slot[a|b]
    slot: int
    sub: str | None = None
    verdict: str                             # same | unsure | diff
    char: str | None = None                  # same 档继承的 surface char
    matched_id: str | None = None            # same 档命中的库条目
    cov: float = 0.0
    wmax: float = 0.0
    candidates: list[tuple[str, float]] = Field(default_factory=list)
    #                                        # unsure 档：字 → cov 先验，降序
    guard: str | None = None                 # never_match | conflict
    n_verified: int = 0


class ColumnMatch(BaseModel):
    col: int
    ok: bool = True
    error: str | None = None
    chars: list[MatchRec] = Field(default_factory=list)


class PageMatch(BaseModel):
    page: int
    db_fingerprint: str = ""                 # 判决是对**哪个库**做的，见模块头
    columns: list[ColumnMatch] = Field(default_factory=list)

    def column(self, col: int) -> ColumnMatch | None:
        return next((c for c in self.columns if c.col == col), None)


class OcrRec(BaseModel):
    id: str
    slot: int
    sub: str | None = None
    topk: list[tuple[str, float]] = Field(default_factory=list)
    #                                        # (字, prob)，已含简→繁扩展
    engine: str = ""


class ColumnOcr(BaseModel):
    col: int
    ok: bool = True
    error: str | None = None
    chars: list[OcrRec] = Field(default_factory=list)


class PageOcr(BaseModel):
    page: int
    engine: str = ""
    columns: list[ColumnOcr] = Field(default_factory=list)

    def column(self, col: int) -> ColumnOcr | None:
        return next((c for c in self.columns if c.col == col), None)


class DecisionRec(BaseModel):
    """一个字位的最终定字 + 证据（Step6）。"""
    id: str
    slot: int
    sub: str | None = None
    char: str | None = None                  # None = 弃权，落回人审
    margin: float = 0.0
    source: str = ""                         # db_same | context | prior | none
    used_context: bool = False
    ranked: list[tuple[str, float]] = Field(default_factory=list)


class ColumnDecision(BaseModel):
    col: int
    ok: bool = True
    error: str | None = None
    chars: list[DecisionRec] = Field(default_factory=list)


class PageDecision(BaseModel):
    page: int
    strategy: str = ""
    corpus_fingerprint: str = ""             # 裁决是用**哪份语料**做的，见 context_decide
    columns: list[ColumnDecision] = Field(default_factory=list)

    def column(self, col: int) -> ColumnDecision | None:
        return next((c for c in self.columns if c.col == col), None)


class AdmitRec(BaseModel):
    """一个字位的进库裁决 + 证据（C1）。进库本身走 Event → glyphdb_admit。"""
    id: str
    slot: int
    sub: str | None = None
    admit: bool = False
    channel: str | None = None          # match_solo | match_solo_ocr | context | ...
    char: str | None = None             # 拟进库的字（字形层，照录图上的形）
    reading: str | None = None
    """文意读法（语义层）。与 `char` 不同就是一次**字形→文意的转换**。

    刻本刻「㫖」而整理本作「旨」、刻「彚」而整理本作「彙」——字形库存前者，
    文本录入用后者，两条线不许互相污染（charset_and_lm.md §四）。整理本参与
    的通道（dual / match_replace / match_ref_weak / match_margin）会填这一栏，
    `char` 仍照录图上的形。None = 与 `char` 相同。
    """
    provenance: str = ""                # match | align | context —— 设计 §3.2 分级
    doubts: list[str] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)


class ColumnAdmit(BaseModel):
    col: int
    ok: bool = True
    error: str | None = None
    chars: list[AdmitRec] = Field(default_factory=list)


class PageAdmit(BaseModel):
    page: int
    n_auto: int = 0
    n_review: int = 0
    n_excluded: int = 0        # 命中排除名单（图块切坏/非字）：不进库也不出审查卡
    columns: list[ColumnAdmit] = Field(default_factory=list)

    def column(self, col: int) -> ColumnAdmit | None:
        return next((c for c in self.columns if c.col == col), None)


GLYPH_MATCH = register_kind(ProductKindSpec(
    id="glyph_match", title="Step5 库匹配判决", storage="numeric", unit="cell",
    schema=PageMatch, coord_space=COLUMN_PX))

OCR_CANDIDATES = register_kind(ProductKindSpec(
    id="ocr_candidates", title="Step5 OCR 候选", storage="numeric", unit="cell",
    schema=PageOcr, coord_space=COLUMN_PX))

CONTEXT_DECISION = register_kind(ProductKindSpec(
    id="context_decision", title="Step6 上下文定字", storage="numeric", unit="cell",
    schema=PageDecision, coord_space=COLUMN_PX))

SEED_ADMIT = register_kind(ProductKindSpec(
    id="seed_admit", title="C1 进库准入裁决", storage="numeric", unit="cell",
    schema=PageAdmit, coord_space=COLUMN_PX))
