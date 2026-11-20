"""候／𠋫 书级刻形判法（全唐文 995ejelvk0，形近字线 2026-11-20）。

全唐文书级码位把 候 统一记成 𠋫（照刻形，sheldon 11-03）。11-19 字形线发现 010:96:3:8 是真 候，形近字线看 001–045 的
264 格：前半多刻 𠋫（亻 右边还有一条通长的第二竖），033 册起多刻真 候（亻 右边只一小丨连 矦）。sheldon 点选 182 格定标签。

判法是几何量，不用网：字块二值化、裁到墨边，左 60% 宽里逐列求「容忍小断笔的最长竖段 / 字高」，取彼此隔开的前 3 个峰，
第二高的峰就是 亻 右边那一竖的长度 `v`。`v < lo` 给 候、`v ≥ hi` 给 𠋫，其间弃权（留人审）。
阈值随书配置走（`config/groups/hou_shape.json`）::

    {"schema": "hou_shape/1", "chars": ["候", "𠋫"], "lo": 0.52, "hi": 0.70}
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

SCHEMA = "hou_shape/1"


def _gaprun(col: np.ndarray, gap: int) -> int:
    """一列里最长的竖段长度，段内空隙 ≤ gap 当连着。"""
    idx = np.flatnonzero(col)
    if not len(idx):
        return 0
    brk = np.flatnonzero(np.diff(idx) > gap)
    starts = np.concatenate(([idx[0]], idx[brk + 1]))
    ends = np.concatenate((idx[brk], [idx[-1]]))
    return int((ends - starts + 1).max())


def second_vertical(gray: np.ndarray, thr: int = 140) -> float | None:
    """字块（灰度）→ 亻 右边第二竖的相对长度；墨太少 → None。"""
    g = np.asarray(gray)
    if g.ndim == 3:
        g = g[..., :3].mean(axis=2)
    a = g < thr
    ys, xs = np.nonzero(a)
    if len(xs) < 50:
        return None
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = a.shape
    gap = max(2, int(0.05 * h))
    n = int(w * 0.6)
    if n < 3:
        return None
    runs = np.array([_gaprun(a[:, x], gap) / h for x in range(n)])
    sep = max(4, int(w * 0.07))
    chosen: list[int] = []
    for x in np.argsort(-runs, kind="stable"):
        if all(abs(int(x) - y) >= sep for y in chosen):
            chosen.append(int(x))
        if len(chosen) == 3:
            break
    v = sorted((runs[x] for x in chosen), reverse=True)
    return float(v[1]) if len(v) > 1 else 0.0


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("schema") != SCHEMA:
        raise ValueError(f"hou_shape：{path} 不是 {SCHEMA}")
    if not float(d["lo"]) <= float(d["hi"]):
        raise ValueError(f"hou_shape：{path} 要 lo ≤ hi")
    return d


def load(path: str) -> dict:
    p = Path(path)
    return _load(str(p), p.stat().st_mtime)


def fingerprint(path: str | None) -> str:
    p = Path(path) if path else None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p and p.exists() else ""


def judge(gray: np.ndarray, model: dict) -> dict:
    """→ {"char": 候|𠋫|None, "why": "agree"|"abstain:mid"|"abstain:no_ink", "v": 第二竖长}。"""
    v = second_vertical(gray, int(model.get("thr", 140)))
    if v is None:
        return {"char": None, "why": "abstain:no_ink"}
    hou, alt = model.get("chars", ["候", "𠋫"])
    ch = hou if v < float(model["lo"]) else alt if v >= float(model["hi"]) else None
    return {"char": ch, "why": "agree" if ch else "abstain:mid", "v": round(v, 4)}


__all__ = ["SCHEMA", "second_vertical", "load", "fingerprint", "judge"]
