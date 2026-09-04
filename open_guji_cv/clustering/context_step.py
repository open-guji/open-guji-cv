"""上下文裁决步（管线独立一步）：候选分布 + 列上下文 → 定字。

## 这一步是什么

上游（OCR / 库匹配 / 整理本）产出**候选先验分布**；本步用同列前文 +
语言模型判断「通不通顺」，在候选集合内挑出定字。它被抽象成独立一步，
是为了能**换着法子做**——n-gram 只是第一个策略，神经 LM、大模型 API
都可以按同一接口接入，然后在同一个测试集上真刀真枪比。

- 测试集：`open-guji-dataset/context-correction`（vol01 进库协议金标
  1681 槽位，候选冻结，human/align 分层）；
- 量法：`scripts/eval_context_correction.py --strategy <名字>`；
- 生产接线：`seeding.seed_book` 的 context 通道。

## 两条铁律（换任何模型都不许破）

1. **字形层不可改写**：只在候选集合内重排，不得引入候选外的字；
   同语义组内选形优先取 OCR/库真正见过的形（semantic_margin 的
   surface_prefs）。语义层产出读法，字形层产出「这一版刻的是什么字」。
2. **门槛化，不做全局重排**：1681 真实槽位实测，对含库匹配证据的强
   先验做无条件重排在任何 λ 下净亏（λ=0.95 仍 救17/坏34）；语义
   margin 过阈才动手（生产阈 0.70：303 条实审全对）。策略可以自定
   margin 的算法，但「拿不准就保持基线」的框架不许拆。

## 怎么加一个新策略

继承 ContextDecider 实现 decide()，在 STRATEGIES 注册；决策依据放进
返回的 Decision（证据纪律：进库时整个 Decision 会写进 evidence）。
然后在 context-correction 集上跑 eval 出数，报 top1_gain 必须连
harmful_flip_rate 一起。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .lm import BaseLM
from .recognize_flow import (LAMBDA, Decision, rank_candidates,
                             semantic_margin)


@dataclass
class ContextResult:
    """一次上下文裁决的完整证据。

    - surface：字形层定字（None = 无候选/策略弃权）；
    - margin：语义层 margin（策略自定义口径，门槛比较用）；
    - decision：核心 Decision（ranked 分布 + 上下文使用情况），进库
      时随 evidence 落库。
    """
    surface: str | None
    margin: float
    decision: Decision


class ContextDecider:
    """策略基类：candidates（已融合先验）+ 前文 → ContextResult。"""

    name = "base"

    def decide(self, priors: dict[str, float],
               context: tuple[str, ...] = (),
               surface_prefs: set[str] | None = None) -> ContextResult:
        raise NotImplementedError


class PriorTop1(ContextDecider):
    """基线策略：不看上下文，先验 top1 直出（margin 也来自先验）。"""

    name = "prior"

    def decide(self, priors, context=(), surface_prefs=None):
        dec = rank_candidates(priors)
        surface, margin = semantic_margin(dec, self._sem, surface_prefs)
        return ContextResult(surface, margin, dec)

    def __init__(self, semantic_fn: Callable[[str], str] | None = None):
        self._sem = semantic_fn or (lambda c: c)


class GatedNgram(ContextDecider):
    """生产策略：n-gram LM（通常为 build_seed_lm 的混合）+ 语义层选形。

    与 seed context 通道逐字节同源：rank_candidates（softmax 融合
    lam·log prior + (1-lam)·LM）→ semantic_margin（同语义异体归并计分、
    字形层保精确异体）。门槛由调用方持（seed 用 DEFAULT_CONTEXT_MARGIN，
    评测用 --gate）——本类只出证据，不定政策。
    """

    name = "gated_ngram"

    def __init__(self, lm: BaseLM, semantic_fn: Callable[[str], str],
                 lam: float = LAMBDA):
        self.lm = lm
        self.semantic_fn = semantic_fn
        self.lam = lam

    def decide(self, priors, context=(), surface_prefs=None):
        dec = rank_candidates(priors, context=context or None, lm=self.lm,
                              semantic_fn=self.semantic_fn, lam=self.lam)
        surface, margin = semantic_margin(dec, self.semantic_fn,
                                          surface_prefs)
        return ContextResult(surface, margin, dec)


class OracleLLM(ContextDecider):
    """大模型裁决（离线答案表驱动）。

    ## 为什么是「答案表」而不是在线调 API

    `confusable-context` 154 题上大模型盲测 98.7%，远高于 n-gram 95.5%、
    字形层 64.3%。但那次是**导出题面、离线作答、再对分**跑出来的
    （`scripts/export_confusable_prompt.py`），不是管线里在线调用。照搬成
    在线调用有三个问题：

    1. **数字不可复现**：模型版本、温度、甚至同一次请求的重试都会变答案，
       而 benchmark 要求「换算法时数字还能比」；
    2. **评测会泄漏**：在线模型见过整理本，等于把金标喂回给被测对象；
    3. 本机没有 API 凭证，接了也跑不了——**没有验收集的算法不许进生产路径**
       （handbook §3 P1）。

    所以这一层做成：**答案表在外面产生，策略只负责消费**。答案表是
    `{字位 id: 选中的字}` 的 JSON，可以来自大模型盲测、也可以来自人裁。
    表里没有的字位一律**弃权**（margin=0），交回 n-gram 或人——
    「拿不准就保持基线」。

    ## 两条铁律照旧

    - **只在候选内选**：答案不在 `priors` 里就当没答（防模型引入候选外的字）；
    - **门槛化**：`margin` 由调用方定政策，本类只出证据。命中时给
      `confidence`（默认 1.0）当 margin，未命中给 0。
    """

    name = "oracle_llm"

    def __init__(self, answers: dict[str, str],
                 semantic_fn: Callable[[str], str] | None = None,
                 fallback: ContextDecider | None = None,
                 confidence: float = 1.0):
        self.answers = answers or {}
        self.semantic_fn = semantic_fn or (lambda c: c)
        self.fallback = fallback
        self.confidence = confidence

    def decide(self, priors, context=(), surface_prefs=None, item_id=""):
        ans = self.answers.get(item_id) if item_id else None
        # 答案必须落在候选内——不在就当没答，绝不引入候选外的字
        if ans and ans in priors:
            ranked = sorted(priors.items(), key=lambda kv: -kv[1])
            dec = Decision(char=ans, margin=self.confidence, ranked=ranked,
                           used_context=True)
            return ContextResult(ans, self.confidence, dec)
        if self.fallback is not None:
            return self.fallback.decide(priors, context, surface_prefs)
        ranked = sorted(priors.items(), key=lambda kv: -kv[1])
        return ContextResult(None, 0.0,
                             Decision(char=None, margin=0.0, ranked=ranked,
                                      used_context=False,
                                      fallback="no_oracle_answer"))


STRATEGIES: dict[str, type[ContextDecider]] = {
    "prior": PriorTop1,
    "gated_ngram": GatedNgram,
    "oracle_llm": OracleLLM,
}


def build_strategy(name: str, *, lm: BaseLM | None = None,
                   semantic_fn: Callable[[str], str] | None = None,
                   lam: float = LAMBDA,
                   answers: dict[str, str] | None = None) -> ContextDecider:
    """按名字构造策略。gated_ngram 需要 lm + semantic_fn。"""
    if name == "prior":
        return PriorTop1(semantic_fn)
    if name == "gated_ngram":
        if lm is None or semantic_fn is None:
            raise ValueError("gated_ngram 需要 lm 与 semantic_fn")
        return GatedNgram(lm, semantic_fn, lam)
    if name == "oracle_llm":
        # 答案表缺席时退回 n-gram：策略在，但不假装有答案
        fb = (GatedNgram(lm, semantic_fn, lam)
              if lm is not None and semantic_fn is not None else None)
        return OracleLLM(answers or {}, semantic_fn, fallback=fb)
    raise KeyError(f"未注册的上下文策略: {name}（可用: {sorted(STRATEGIES)}）")
