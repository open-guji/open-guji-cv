# -*- coding: utf-8 -*-
"""日／曰 近形组 v2 答案表（overview#441，Z-jys）：离线多模型判读 → 管线只查表，不在线调模型。

表（json，`{"cells": {cell_id: {...}}}`，由 `research/char_groups/ry/build_cache.py` 生成）每格：
    {"ctx": <ctx_key>, "ver": "ry-v2", "votes": {"muse": [a, b], "gemini": [a, b], "haiku": [a]}}
票面 ∈ {日, 曰, 不确定, None}；`None`＝该遍没出结果。

放行判据（`decide`）：muse、gemini 都给字、两遍都在、四票同字；haiku 只有否决权（给了另一个字即否决，
弃权／缺票不否决）。缺格、上下文哈希对不上、版本不符、任一遍弃权／不一致 → `char=None` 并写明原因。
本模块只给证据；管线已不读它（原开关 `seed_admit.ry_group` 已于 2026-10-18 并进 `group_flow` 删除），只留给离线评测（`groups/backends.RyV2TableBackend`）。"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .ji_yi_si_clf import ctx_key

FAMILY = frozenset("日曰")
PROMPT_VER = "ry-v2"
MAIN_MODELS = ("muse", "gemini")


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))["cells"]


def decide(cache_path: str, cell_id: str, left: str, right: str) -> dict | None:
    """查表 → `{"char": 字|None, "why": 原因, "votes": …}`；没配表返回 None。"""
    if not cache_path:
        return None
    e = _load(cache_path).get(cell_id)
    if not e:
        return {"char": None, "why": "cache_miss"}
    if e.get("ctx") != ctx_key(left, right):
        return {"char": None, "why": "ctx_mismatch"}
    if e.get("ver") != PROMPT_VER:
        return {"char": None, "why": "ver_mismatch"}
    votes = e.get("votes") or {}
    mains: list = []
    for m in MAIN_MODELS:
        v = (votes.get(m) or [None, None])[:2]
        if len(v) < 2 or any(x not in FAMILY for x in v):
            return {"char": None, "why": f"abstain:{m}", "votes": votes}
        mains += v
    if len(set(mains)) != 1:
        return {"char": None, "why": "disagree", "votes": votes}
    ch = mains[0]
    if any(x in FAMILY and x != ch for x in (votes.get("haiku") or [])):
        return {"char": None, "why": "haiku_veto", "votes": votes}
    return {"char": ch, "why": "muse∧gemini 两遍一致", "votes": votes}
