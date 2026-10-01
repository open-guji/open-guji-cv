# -*- coding: utf-8 -*-
"""Step6（上下文定字＋弃权）· 逐 (格, 候选) 信号抽取。X1 实验件，默认不接线。

一格 → 每个候选一行特征。口径刻意与 ``shadow/signals.py`` 同构：``SIGNAL_VERSION``
随特征集变化而变，模型文件里记下它，线上线下不一致就拒载。

只用「冻结候选 + 上下文 + LM」能算的信号（context-correction 金标里就这些）。
**故意不含**「整理本字是否相等」：align 出身的金标本来就是从整理本对齐来的，
这个特征在 align 格上等于答案（循环性，见 scripts/calibrate_margin.py 头）。
线上有整理本时可以补，但补之前要在 human 格上单独验。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

SIGNAL_VERSION = "x1-1"

FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "ocr": ("p", "logp", "rank", "p_rel", "gap_top", "gap_next", "ncand", "is_rapid"),
    "sem": ("grp_mass", "grp_size", "in_top_grp", "n_groups"),
    "lm": ("lg_c", "lg_rank", "lb_c", "lb_rank", "lm_c", "lm_rank", "lm_gap_top", "lm_gap_base"),
    "win": ("w_c", "w_rank", "w_gap_base"),
    "conf": ("conf_top", "jys"),
    "rule": ("rule_p", "rule_pick", "rule_margin"),
}
FEATURES: tuple[str, ...] = tuple(f for g in FEATURE_GROUPS.values() for f in g)
JYS = frozenset("己已巳")


@dataclass
class SignalCtx:
    semantic: Callable[[str], str]
    partners: dict
    lm_gen: object | None          # 通用 LM（可 None）
    lm_book: object | None         # 本书 LM（None = 没有本书语料的情形，lb_* 恒 0）
    lm_mix: object                 # 现行混合 LM（rule_* 与 lm_* 用）
    lam: float = 0.55


def _centered(v: list[float]) -> list[float]:
    m = max(v)
    return [x - m for x in v]


def _rank(v: list[float]) -> list[int]:
    order = sorted(range(len(v)), key=lambda i: -v[i])
    r = [0] * len(v)
    for k, i in enumerate(order):
        r[i] = k
    return r


def slot_rows(cands: list[dict], prev: tuple[str, ...], nxt: tuple[str, ...],
              ctx: SignalCtx) -> np.ndarray:
    """cands: [{char, prob, source}]（已按 prob 降序即基线顺序）。

    prev = 前文已定字（最近在最后）；nxt = 后文**基线首选**字（非金标，线上可得）。
    返回 (len(cands), len(FEATURES)) 矩阵。
    """
    from ..clustering.recognize_flow import rank_candidates, semantic_margin

    chars = [c["char"] for c in cands]
    probs = [max(float(c["prob"]), 1e-9) for c in cands]
    n = len(chars)
    top = max(probs)
    srt = sorted(probs, reverse=True)
    sem = [ctx.semantic(c) for c in chars]
    gmass: dict[str, float] = {}
    gsize: dict[str, int] = {}
    for s, p in zip(sem, probs):
        gmass[s] = gmass.get(s, 0.0) + p
        gsize[s] = gsize.get(s, 0) + 1
    top_grp = max(gmass, key=lambda s: gmass[s])

    pv = tuple(prev[-2:])

    def lp(lm, ch):
        return lm.logp(ch, pv) if lm is not None else 0.0

    def window(lm, ch):
        # log P(ch|prev) + log P(n1|prev[-1],ch) + log P(n2|ch,n1)
        t = lp(lm, ch)
        if lm is None:
            return 0.0
        if len(nxt) >= 1:
            t += lm.logp(nxt[0], (pv[-1:] if pv else ()) + (ch,))
        if len(nxt) >= 2:
            t += lm.logp(nxt[1], (ch, nxt[0]))
        return t

    lg = _centered([lp(ctx.lm_gen, c) for c in chars])
    lb = _centered([lp(ctx.lm_book, c) for c in chars])
    lm_ = [lp(ctx.lm_mix, c) for c in chars]
    lm_c = _centered(lm_)
    w = [window(ctx.lm_mix, c) for c in chars]
    w_c = _centered(w)
    lgr, lbr, lmr, wr = _rank(lg), _rank(lb), _rank(lm_), _rank(w)

    # 现行规则（作为特征喂入 = 堆叠；消融里可单独关）
    priors = {c: p for c, p in zip(chars, probs)}
    dec = rank_candidates(priors, context=pv or None, lm=ctx.lm_mix,
                          semantic_fn=ctx.semantic, lam=ctx.lam)
    pick, margin = semantic_margin(dec, ctx.semantic)
    rp = dict(dec.ranked)

    base = chars[0]
    base_part = ctx.partners.get(base, frozenset())
    X = np.zeros((n, len(FEATURES)), dtype=np.float64)
    ix = {f: i for i, f in enumerate(FEATURES)}
    for k, c in enumerate(chars):
        r = {
            "p": probs[k], "logp": math.log(probs[k]), "rank": k,
            "p_rel": probs[k] / top, "gap_top": top - probs[k],
            "gap_next": (srt[0] - srt[1]) if (n > 1 and probs[k] == srt[0]) else 0.0,
            "ncand": n, "is_rapid": float(cands[k].get("source") in ("rapidocr", "ocr")),
            "grp_mass": gmass[sem[k]], "grp_size": gsize[sem[k]],
            "in_top_grp": float(sem[k] == top_grp), "n_groups": len(gmass),
            "lg_c": lg[k], "lg_rank": lgr[k], "lb_c": lb[k], "lb_rank": lbr[k],
            "lm_c": lm_c[k], "lm_rank": lmr[k],
            "lm_gap_top": max(lm_) - lm_[k], "lm_gap_base": lm_[k] - lm_[0],
            "w_c": w_c[k], "w_rank": wr[k], "w_gap_base": w[k] - w[0],
            "conf_top": float(k > 0 and (c in base_part or base in ctx.partners.get(c, frozenset()))),
            "jys": float(c in JYS),
            "rule_p": rp.get(c, 0.0), "rule_pick": float(c == pick),
            "rule_margin": margin if c == pick else -margin,
        }
        for f, v in r.items():
            X[k, ix[f]] = v
    return X
