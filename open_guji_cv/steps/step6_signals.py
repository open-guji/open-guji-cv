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

from dataclasses import dataclass
from typing import Callable


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


