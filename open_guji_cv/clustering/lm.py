"""M5 语言模型后端（语义层打分）。

框架期实现：纯 Python 字符 n-gram + stupid backoff，零依赖、确定性、可单测。
后续可注册 kenlm / masked-lm 后端（接口不变）。

约定：LM 的训练与打分全部在语义层（异体字已正字化）进行。

## 混合模型（`InterpolatedLM`）

单一语料训不出好用的古籍 LM：通用古文语料量大但不认识本书的书名、
人名、术语；本书语料认识这些但量小、且（若来自自举转写）带识别噪声。
把两者**按权重线性插值**：通用低权重兜底，本书高权重加尖。

**为什么是线性插值而不是对数线性（几何）混合。** 对数线性混合是
``Σ wᵢ·log pᵢ``，任何一个分量给出接近零的概率都会把结果拖到零——
通用语料没收录的本书专名会被通用 LM 一票否决，恰好否决掉本书 LM
唯一的贡献。线性混合 ``log Σ wᵢ·pᵢ`` 相反：只要有一个分量给了质量，
结果就有质量，这才是「兜底 + 加尖」想要的行为。

**这不是给自举 LM 平反。** 消融实验（见 `context_refine` 文档）证明
自举语料（约 15% 识别噪声）**单独**用作 LM 是净有害的。混合改变的是
它的用法：噪声分量拿低权重、且有一个干净的大分量在旁边压着，才谈得上
安全。权重必须在 `context-correction` 测试集上量出来，不能拍。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

BOS = "<s>"


class BaseLM:
    name: str = "base"

    def logp(self, char: str, context: tuple[str, ...]) -> float:
        """log P(char | context)。context 为语义层前文（最近的在最后）。"""
        raise NotImplementedError


class UniformLM(BaseLM):
    """无语料时的兜底：全 candidates 均匀分（LM 项退化为常数）。"""

    name = "uniform"

    def logp(self, char: str, context: tuple[str, ...]) -> float:
        return 0.0


class CharNgramLM(BaseLM):
    """字符 n-gram + stupid backoff（默认 3-gram）。"""

    name = "ngram"

    def __init__(self, order: int = 3, backoff: float = 0.4):
        self.order = order
        self.backoff = backoff
        # counts[k][context_str][char] ；k = len(context)
        self.counts: list[dict[str, dict[str, int]]] = [
            {} for _ in range(order)]
        self.vocab: set[str] = set()

    def train(self, texts: Iterable[str]) -> None:
        for text in texts:
            chars = [BOS] * (self.order - 1) + list(text)
            for i in range(self.order - 1, len(chars)):
                ch = chars[i]
                self.vocab.add(ch)
                for k in range(self.order):
                    ctx = "".join(chars[i - k:i])
                    table = self.counts[k].setdefault(ctx, {})
                    table[ch] = table.get(ch, 0) + 1

    def logp(self, char: str, context: tuple[str, ...]) -> float:
        v = max(1, len(self.vocab))
        penalty = 0.0
        for k in range(min(self.order - 1, len(context)), -1, -1):
            ctx = "".join(context[len(context) - k:]) if k else ""
            table = self.counts[k].get(ctx)
            if table:
                total = sum(table.values())
                cnt = table.get(char, 0)
                if cnt:
                    return penalty + math.log(cnt / total)
            penalty += math.log(self.backoff)
        # 全级回退失败：加一平滑的 unigram 下界
        return penalty + math.log(1.0 / (v + 1))

    # ── 持久化 ────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        data = {"order": self.order, "backoff": self.backoff,
                "vocab": sorted(self.vocab), "counts": self.counts}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    @classmethod
    def load(cls, path: str | Path) -> "CharNgramLM":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        lm = cls(order=data["order"], backoff=data["backoff"])
        lm.vocab = set(data["vocab"])
        lm.counts = data["counts"]
        return lm


    # ── 剪枝 ────────────────────────────────────────────

    def prune(self, min_count: int = 2, keep_order: int = 1) -> "CharNgramLM":
        """丢掉高阶上下文里只出现过一次的计数（就地修改，返回自身）。

        大语料的三元组绝大多数是 hapax：它们几乎不带信息（下次遇到同一
        上下文的概率极低），却占掉绝大部分内存。低阶（``k <= keep_order``，
        默认保留一元）不剪——回退链的兜底全靠它，剪了会让没见过的
        上下文直接掉到平滑下界。
        """
        for k in range(len(self.counts) - 1, keep_order, -1):
            table = self.counts[k]
            for ctx in list(table):
                kept = {c: n for c, n in table[ctx].items() if n >= min_count}
                if kept:
                    table[ctx] = kept
                else:
                    del table[ctx]
        return self


class InterpolatedLM(BaseLM):
    """多个 LM 的线性插值：``p = Σ wᵢ·pᵢ / Σ wᵢ``。

    权重不必归一，构造时自动归一。分量为空时退化为 UniformLM 的行为。
    """

    name = "mixture"

    def __init__(self, components: list[tuple[BaseLM, float]]):
        total = sum(w for _, w in components if w > 0) or 1.0
        self.components = [(lm, w / total) for lm, w in components if w > 0]
        if self.components:
            self.name = "mix(" + ",".join(
                f"{lm.name}:{w:.2f}" for lm, w in self.components) + ")"

    def logp(self, char: str, context: tuple[str, ...]) -> float:
        if not self.components:
            return 0.0
        # log Σ wᵢ·exp(logpᵢ)，用 logsumexp 形式避免下溢
        terms = [math.log(w) + lm.logp(char, context)
                 for lm, w in self.components]
        top = max(terms)
        return top + math.log(sum(math.exp(t - top) for t in terms))


LM_BACKENDS: dict[str, type[BaseLM]] = {
    "uniform": UniformLM,
    "ngram": CharNgramLM,
    "mixture": InterpolatedLM,
}


def train_ngram(texts: Iterable[str], order: int = 3,
                min_count: int = 1) -> CharNgramLM:
    """便捷构造：训练 + 可选剪枝。"""
    lm = CharNgramLM(order=order)
    lm.train(texts)
    if min_count > 1:
        lm.prune(min_count)
    return lm
