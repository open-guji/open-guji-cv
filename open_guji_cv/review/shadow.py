# -*- coding: utf-8 -*-
"""影子放行模型的预测文件（overview#269）：给「对齐改字层 · 网格」排序＋预勾用。

影子模型（`research/shadow_admit/`，梯度提升树）的价值在**排序和预选，不在自动改判**：
网格里影子把握 ≥ 0.9 且影子字 == 整理本字的卡排最前、预先标上「影子预勾」，人仍要点提交。

文件约定（缺省不存在，一切照旧、不报错）：`<ws>/cache/shadow/<book>.json`

    {"version": 1, "book": "vol03", "cells": {"vol03:12:3:5": {"char": "之", "conf": 0.97}, ...}}

`cells` 的键 = 字位 id（与卡片 `id` 同），`char` = 影子字，`conf` = 影子把握度（0~1）。
由 `research/shadow_admit/export_for_cards.py` 从 `shadow_picks.jsonl` 导出。
"""
from __future__ import annotations

import json
from pathlib import Path

SHADOW_THR = 0.9            # 用户 2026-09-30 拍板：≥0.9 且等于整理本字才预勾


def shadow_path(book: str) -> Path:
    from ..core.workspace import cache_root
    from ..feedback.events import EventLog
    return Path(cache_root()) / "shadow" / f"{EventLog.safe_batch_name(book)}.json"


def shadow_sig(book: str) -> str | None:
    """文件指纹（进卡片缓存键：预测文件一换，缓存自动失效）；文件不存在 → None。"""
    try:
        s = shadow_path(book).stat()
    except OSError:
        return None
    return f"{s.st_mtime_ns}:{s.st_size}"


def load_shadow(book: str) -> dict[str, dict] | None:
    """→ `{字位 id: {"char", "conf"}}`；文件不存在／损坏／格式不对 → None（当没有）。"""
    try:
        doc = json.loads(shadow_path(book).read_text(encoding="utf-8"))
        cells = doc["cells"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(cells, dict):
        return None
    out: dict[str, dict] = {}
    for k, v in cells.items():
        try:
            out[str(k)] = {"char": str(v["char"]), "conf": float(v["conf"])}
        except (KeyError, TypeError, ValueError):
            continue
    return out


def shadow_view(entry: dict | None, ref_char: str | None) -> dict | None:
    """一张卡的影子字段：`{char, conf, pre}`；`pre` = 该预勾（conf≥阈值 且 影子字 == 整理本字）。"""
    if not entry:
        return None
    conf = round(entry["conf"], 4)
    return {"char": entry["char"], "conf": conf,
            "pre": bool(ref_char) and entry["char"] == ref_char and conf >= SHADOW_THR}
