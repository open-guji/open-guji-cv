"""4b 的填空模型：SikuRoBERTa（不微调，钉 revision）对「前文 [MASK] 后文」的字表 log 概率，与图像分融合。

候选字线测试集 `char-candidates` 上量过的口径（2026-11-27，CV3）：
- 语义分＝字及其异体族成员在词表里的最大 logp（`HanziDB.family`），不在词表的字取池里的中位数、下限 −12；
- 融合分＝图像分 ＋ w·语义分，w＝0.005（`DEFAULT_W`）。w 大了会把图像对的字挤下去，伤害率（图像首位已对却被换掉）随 w 涨。

重依赖（torch、transformers）只在第一次 `shared()` 时 import；缺件返回 None，调用方当「没排」。
"""
from __future__ import annotations

import logging
from functools import lru_cache

LM_NAME = "SIKU-BERT/sikuroberta"
LM_REV = "bb25260d5c321924fe4fb353c09191c0aaf5c5c6"
FLOOR = -12.0
DEFAULT_W = 0.005
WINDOW = 24            # 左右各取几字
MISSING = "□"          # 邻格没有字（没认出、切坏）：换成 [UNK]
_log = logging.getLogger(__name__)


def model_version(w: float = DEFAULT_W) -> str:
    return f"siku@{LM_REV[:8]}/w{w:g}"


def fuse(pool: list[tuple[str, float]], sem: dict[str, float], w: float = DEFAULT_W) -> list[tuple[str, float, float | None]]:
    """pool＝[(字, 图像分)]，sem＝{字: logp}。→ [(字, 融合分, logp 或 None)]，按融合分降序（同分保原序）。"""
    vals = sorted(sem[c] for c, _ in pool if c in sem)
    neutral = vals[len(vals) // 2] if vals else 0.0
    out = [(c, s + w * max(sem.get(c, neutral), FLOOR), sem.get(c)) for c, s in pool]
    return sorted(out, key=lambda t: -t[1])


class CtxLM:
    def __init__(self):
        import torch
        from transformers import AutoModelForMaskedLM, AutoTokenizer

        from ..hanzi.db import shared as hanzi
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(LM_NAME, revision=LM_REV)
        self.model = AutoModelForMaskedLM.from_pretrained(LM_NAME, revision=LM_REV).eval()
        self.vocab = self.tok.get_vocab()
        self.hz = hanzi()
        self._fam: dict[str, set] = {}
        self._cache: dict = {}

    def family(self, c: str) -> set:
        if c not in self._fam:
            try:
                self._fam[c] = {c} | set(self.hz.family(c).keys())
            except Exception:  # noqa: BLE001 —— 族查不到就只看本字
                self._fam[c] = {c}
        return self._fam[c]

    def _logp(self, left: str, right: str):
        key = (left, right)
        if key in self._cache:
            return self._cache[key]
        torch, tok = self.torch, self.tok
        a = left[-WINDOW:].replace(MISSING, "[UNK]")
        b = right[:WINDOW].replace(MISSING, "[UNK]")
        enc = tok(a + tok.mask_token + b, return_tensors="pt", truncation=True, max_length=128)
        mp = (enc.input_ids[0] == tok.mask_token_id).nonzero()
        val = None
        if len(mp):
            with torch.no_grad():
                val = self.model(**enc).logits[0, mp[0, 0]].log_softmax(-1)
        if len(self._cache) > 20000:
            self._cache.clear()
        self._cache[key] = val
        return val

    def sem(self, left: str, right: str, chars) -> dict[str, float] | None:
        lg = self._logp(left, right)
        if lg is None:
            return None
        out = {}
        for c in chars:
            vs = [float(lg[self.vocab[x]]) for x in self.family(c) if x in self.vocab]
            if vs:
                out[c] = max(vs)
        return out


@lru_cache(maxsize=1)
def shared() -> CtxLM | None:
    try:
        return CtxLM()
    except Exception:  # noqa: BLE001 —— 缺 torch／transformers／权重：4b 这一路没排，不拖垮整步
        _log.warning("4b 填空模型加载失败（%s）：context_rank 全部记 ran=False；查 torch／transformers／huggingface 缓存", LM_NAME)
        return None
