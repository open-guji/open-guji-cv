"""字形库优先架构的 unsure/diff 分支裁决（glyph_db_first_design.md §2/§7 第 4 步）。

`GlyphMatcher.match` 三档里的 same 档在 match.py 已闭环（继承库条目）；
本模块接住剩下两档：

- **unsure**：候选集 = 库 unsure 命中的字（cov 当先验）∪ OCR top-k
  （s2t 扩展后，prob 当先验），交上下文/LM 融合打分；
- **diff**：同构，但候选只有 OCR top-k——库里可能根本没有这个字。

全部是**现有件的重编排**（设计 §7 第 4 步明说），不新造机制：

- 融合公式沿用 context_rank.beam_search 的
  ``score = λ·log P_prior + (1-λ)·log P_lm(semantic | context)``，
  λ 默认取 context_rank.LAMBDA；
- s2t 候选扩展复用 candidates.traditional_candidates（PP-OCR 简体字表
  偏差的既有修正）；
- 来源先验权重沿用 candidates.SOURCE_WEIGHTS 的相对比例
  （glyph_knn 3.0 : ocr 1.5）；
- LM 后端即 lm.BaseLM（CharNgramLM / InterpolatedLM / UniformLM 均可）。

与 beam_search 的分工：beam_search 做整列联合解码（多槽位互相解释），
本模块做**单字位、上下文已定**的裁决——库优先流程里前面的字位已经
定字（same 继承或先前裁决），当前字位只需在自己的候选集里挑，
不需要 beam。margin 因此有干净的定义（见 Decision.margin）。

上下文取法：同页同列**相邻已定字位**的当前最优字构成窗口（LM 是前向
n-gram，取前文 idx 升序最近若干字），由 ColumnContext 维护；拿不到
上下文（页首/列首/调用方没给）时退化为**纯先验融合**（λ=1 等价），
Decision.used_context=False 注明。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from .candidates import traditional_candidates
from .context_rank import LAMBDA
from .lm import BaseLM
from .match import MatchResult

# 来源先验权重：沿用 candidates.SOURCE_WEIGHTS 的相对比例（可靠性先验，
# glyph_knn 是人工/上下文验证过的字形，OCR 是简体模型的猜测）。
DB_WEIGHT = 3.0
OCR_WEIGHT = 1.5
DEFAULT_TOPK = 5


@dataclass
class Decision:
    """一次 unsure/diff 裁决的完整证据（设计 §3 纪律 1：逐实例证据）。

    margin 的定义（在此写死，calibrate_margin.py 的标定与库准入阈都
    以此为准）：**融合得分 softmax 归一后 top1 与 top2 的概率差**
    ``margin = p(1st) - p(2nd)``；候选只有一个时 margin = p(1st) = 1.0。

    为什么是概率差而不是对数比：softmax 概率差与 context_rank 现有的
    margin（beam 后验差）同量纲、同阈值习惯（MARGIN_THRESHOLD=0.25 的
    经验直接可迁移）。标定实测（scripts/calibrate_margin.py，vol02
    册内协议，n=2518 裁决）两定义秩相关 0.995，在精度 ≥0.999 的准入线
    下可拿覆盖为 概率差 16.6% vs 对数比 19.2%——差异只有一个错例
    （七/匕 恰好骑在 lr=5.0 网格线下方），在单错例噪声之内，不构成
    换定义的证据；概率差有界 [0,1] 更好定桶，故用它。标定出的准入阈
    见 margin_calibration 报告（当前推荐 **margin ≥ 0.99**）。
    """

    char: str | None                       # 裁决字；无候选时 None
    margin: float                          # 见上，定义写死
    ranked: list[tuple[str, float]] = field(default_factory=list)
    #                                      # (char, 归一后融合概率)，降序
    branch: str = "unsure"                 # "unsure" | "diff"
    used_context: bool = False             # False = 退化为纯先验融合
    fallback: str | None = None            # "no_candidates" | "no_context"

    def to_dict(self) -> dict:
        return {"char": self.char, "margin": round(self.margin, 4),
                "ranked": [[c, round(p, 4)] for c, p in self.ranked],
                "branch": self.branch, "used_context": self.used_context,
                "fallback": self.fallback}


def fuse_priors(db_candidates: list[tuple[str, float]],
                ocr_topk: list[tuple[str, float]],
                w_db: float = DB_WEIGHT, w_ocr: float = OCR_WEIGHT,
                s2t: bool = True) -> dict[str, float]:
    """库候选 ∪ OCR top-k → 归一化先验分布（纯函数）。

    - 库候选：(char, cov)，cov 直接当先验强度；
    - OCR top-k：(char, prob)，先过 traditional_candidates 做 s2t 扩展
      （简体输出还原为繁体候选，一简多繁全给、权重照旧表）；
    - 同字多来源相加（库与 OCR 都指向同一个字 = 更强）。
    """
    score: dict[str, float] = {}
    for ch, cov in db_candidates:
        score[ch] = score.get(ch, 0.0) + w_db * max(cov, 0.0)
    for ch, p in ocr_topk:
        forms = traditional_candidates(ch) if s2t else [(ch, 1.0)]
        for form, w in forms:
            score[form] = score.get(form, 0.0) + w_ocr * max(p, 0.0) * w
    total = sum(score.values())
    if total <= 0:
        n = len(score)
        return {c: 1.0 / n for c in score} if n else {}
    return {c: s / total for c, s in score.items()}


def _decide(priors: dict[str, float], branch: str,
            context: tuple[str, ...] | None, lm: BaseLM | None,
            semantic_fn: Callable[[str], str] | None,
            lam: float) -> Decision:
    """先验分布 + 上下文/LM → Decision（融合打分核心，纯函数）。

    score = λ·log P_prior + (1-λ)·log P_lm(semantic | context)，softmax
    归一。context 为 None/空 或 lm 为 None 时退化为纯先验融合
    （softmax(log p) == p，先验分布原样成为后验）。
    """
    if not priors:
        return Decision(None, 0.0, [], branch, False, "no_candidates")
    sem = semantic_fn or (lambda c: c)
    use_ctx = bool(context) and lm is not None
    scores: dict[str, float] = {}
    if use_ctx:
        ctx = tuple(sem(c) for c in context)
        for ch, p in priors.items():
            scores[ch] = (lam * math.log(max(p, 1e-9))
                          + (1.0 - lam) * lm.logp(sem(ch), ctx))
    else:
        for ch, p in priors.items():
            scores[ch] = math.log(max(p, 1e-9))
    top = max(scores.values())
    exp = {ch: math.exp(s - top) for ch, s in scores.items()}
    z = sum(exp.values())
    ranked = sorted(((ch, e / z) for ch, e in exp.items()),
                    key=lambda t: -t[1])
    margin = ranked[0][1] - (ranked[1][1] if len(ranked) > 1 else 0.0)
    return Decision(ranked[0][0], margin, ranked, branch, use_ctx,
                    None if use_ctx else "no_context")


def decide_unsure(match_result: MatchResult,
                  ocr_topk: list[tuple[str, float]],
                  context: tuple[str, ...] | None = None,
                  lm: BaseLM | None = None,
                  semantic_fn: Callable[[str], str] | None = None,
                  lam: float = LAMBDA,
                  w_db: float = DB_WEIGHT, w_ocr: float = OCR_WEIGHT,
                  s2t: bool = True) -> Decision:
    """unsure 档裁决：库候选（cov 先验）∪ OCR top-k（prob 先验）→ 融合。

    Args:
        match_result: GlyphMatcher.match 的 unsure 档结果，其 .candidates
            即库 kNN 命中的 (char, cov)（含护栏降档补入的对家字）。
        ocr_topk: RapidOcrSource.rec_topk 的原始输出（简体，s2t 在内部
            经 traditional_candidates 扩展；已转繁的输入也无害）。
        context: 同页同列相邻**已定**字位的字（字形层，前文在前、
            最近的在最后；ColumnContext.window 直接可用）。None/空 →
            纯先验融合退化路径。
        lm: 语义层 LM；semantic_fn: 字形→语义映射（默认恒等，
            通常传 VariantMap.semantic）。
        lam: 先验/LM 融合权重（context_rank.LAMBDA 同义）。
    """
    priors = fuse_priors(match_result.candidates, ocr_topk,
                         w_db=w_db, w_ocr=w_ocr, s2t=s2t)
    return _decide(priors, "unsure", context, lm, semantic_fn, lam)


def decide_diff(ocr_topk: list[tuple[str, float]],
                context: tuple[str, ...] | None = None,
                lm: BaseLM | None = None,
                semantic_fn: Callable[[str], str] | None = None,
                lam: float = LAMBDA,
                w_ocr: float = OCR_WEIGHT,
                s2t: bool = True) -> Decision:
    """diff 档裁决：候选只有 OCR top-k——库里可能没有这个字。

    与 decide_unsure 同构（同一融合核心），差别仅是没有库候选。
    OCR 一个字都没给出时返回 Decision(char=None, fallback="no_candidates")
    ——这类实例只能进审查队列。
    """
    priors = fuse_priors([], ocr_topk, w_ocr=w_ocr, s2t=s2t)
    return _decide(priors, "diff", context, lm, semantic_fn, lam)


class ColumnContext:
    """同页同列已定字位的滚动窗口（上下文的取法，见模块 docstring）。

    按 (page, col) 维护 idx → 当前最优字；window() 取 idx 严格小于
    当前字位、已定的最近 size 个字，按 idx 升序返回（前向 LM 的
    context 约定：最近的在最后）。乱序处理也安全——只取「已定且在
    前文」的字位，处理顺序不同只影响窗口的满度，不会把后文混进来。
    """

    def __init__(self, size: int = 4):
        self.size = size
        self._cols: dict[tuple[str, int], dict[int, str]] = {}

    def record(self, page: str, col: int, idx: int, char: str) -> None:
        """登记一个字位的当前最优字（same 继承字与裁决字都应登记）。"""
        self._cols.setdefault((page, col), {})[idx] = char

    def window(self, page: str, col: int, idx: int) -> tuple[str, ...]:
        decided = self._cols.get((page, col))
        if not decided:
            return ()
        prior_idx = sorted(i for i in decided if i < idx)[-self.size:]
        return tuple(decided[i] for i in prior_idx)
