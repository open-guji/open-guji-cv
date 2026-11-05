# -*- coding: utf-8 -*-
"""评测里「图上分不开」的字组折叠（Sheldon 2026-11-05）。

己已巳、日曰两组在刻本图上就是分不开的（字组流程 `groups.registry` 的 `jys`、`ry` 按文意定，不靠图）。
图形评测（5a 库匹配、5a 判同对、5b 候选、L2 证人）里：**匹配到同组任一个字都算对**，
不单独统计组内的正确率。其他形近组（千/干、于/干、十/士、大/太……）照旧要分开。

只给评测脚本用，不进包（`open_guji_cv` 里的代码一动，各步指纹就要变）。
"""
from __future__ import annotations

# 组 → 代表字。成员取自 groups.registry 的 jys／ry；写死是为了评测口径不随字组表悄悄变。
GROUPS = ("己已巳", "日曰")
FOLD: dict[str, str] = {c: g[0] for g in GROUPS for c in g}


def fold(ch: str) -> str:
    return FOLD.get(ch, ch)


def same(a: str, b: str) -> bool:
    return fold(a) == fold(b)


def in_group(ch: str) -> bool:
    return ch in FOLD
