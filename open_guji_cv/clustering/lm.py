"""M5 语言模型后端（语义层打分）。

框架期实现：纯 Python 字符 n-gram + stupid backoff，零依赖、确定性、可单测。
后续可注册 kenlm / masked-lm 后端（接口不变）。

约定：LM 的训练与打分全部在语义层（异体字已正字化）进行。
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


LM_BACKENDS: dict[str, type[BaseLM]] = {
    "uniform": UniformLM,
    "ngram": CharNgramLM,
}
