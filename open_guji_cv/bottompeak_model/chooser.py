# -*- coding: utf-8 -*-
"""选峰回调 + 硬护栏。任何异常、候选不足、护栏不过 → 原样返回现役线（弃权，绝不因模型出错改产物）。

护栏（都在模型外、不看模型分数）：
1. 候选终点不得比现役终点靠上超过 `up_slack`（单侧口径：宁下勿上）；
2. 候选终点不得比现役终点靠下超过 `down_max`；
3. 模型概率要比现役线候选高 `margin`、且不低于 `min_prob` 才换。
"""
from __future__ import annotations

from ..utils.peak_line_search import LineMatch
from .signals import enumerate_candidates


def select(finals, rule_k: int, probs, guard: dict) -> int:
    """纯函数：硬护栏 + 模型概率 → 选中的候选下标（== rule_k 表示保持现役）。训练脚本离线评测也调它。"""
    best, best_p = rule_k, -1.0
    for k, f in enumerate(finals):
        d = f - finals[rule_k]
        if d < -guard["up_slack"] or d > guard["down_max"]:
            continue
        if probs[k] > best_p:
            best, best_p = k, float(probs[k])
    if best == rule_k:
        return rule_k
    if best_p < guard["min_prob"] or best_p - float(probs[rule_k]) < guard["margin"]:
        return rule_k
    return best


def choose(model, mask, cur: LineMatch, verticals, book_gap, lo: int, hi: int,
           top_pos: float | None) -> tuple[LineMatch, dict]:
    """返回 (线, 证据)。证据里 `reason`：kept | switched | abstain:<why>。"""
    try:
        cands = enumerate_candidates(mask, cur, verticals, book_gap, lo, hi, top_pos)
        if len(cands) < 2:
            return cur, {"reason": "abstain:few_candidates"}
        k_rule = next((k for k, c in enumerate(cands) if c["feats"]["is_rule"] > 0), None)
        if k_rule is None:
            return cur, {"reason": "abstain:no_rule_candidate"}
        p = model.probs(cands)
        k = select([c["final"] for c in cands], k_rule, p, model.guard)
        if k == k_rule:
            return cur, {"reason": "kept", "p_rule": float(p[k_rule])}
        return cands[k]["line"], {"reason": "switched", "p_rule": float(p[k_rule]), "p_best": float(p[k]),
                                  "shift": cands[k]["final"] - cands[k_rule]["final"]}
    except Exception as e:                      # noqa: BLE001
        return cur, {"reason": f"abstain:error:{type(e).__name__}"}


def make_chooser(model, top_pos: float | None):
    def _cb(mask, cur, verticals, book_gap, lo, hi):
        line, _ = choose(model, mask, cur, verticals, book_gap, lo, hi, top_pos)
        return line
    return _cb
