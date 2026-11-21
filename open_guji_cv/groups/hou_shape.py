"""候／𠋫 书级刻形判法（全唐文 995ejelvk0，形近字线 2026-11-20）。

全唐文书级码位把 候 统一记成 𠋫（照刻形，sheldon 11-03）。11-19 字形线发现 010:96:3:8 是真 候，形近字线看 001–045 的
264 格：前半多刻 𠋫（亻 右边还有一条通长的第二竖），033 册起多刻真 候（亻 右边只一小丨连 矦）。sheldon 点选 182 格定标签。

判法是几何量，不用网：字块二值化、裁到墨边，左 60% 宽里逐列求「容忍小断笔的最长竖段 / 字高」，取彼此隔开的前 3 个峰，
第二高的峰就是 亻 右边那一竖的长度 `v`。`v < lo` 给 候、`v ≥ hi` 给 𠋫，其间弃权（留人审）。
阈值随书配置走（`config/groups/hou_shape.json`）::

    {"schema": "hou_shape/1", "chars": ["候", "𠋫"], "lo": 0.52, "hi": 0.70}

`hou_shape/2`（形近字线 11-21）：046–053 的刻工第二竖偏长，几何阈值分不开（e1 中间档 30 格里 sheldon 点 候 25 格）。
改用小卷积网（结构、numpy 前向同 `groups.wu_shape`）：字块灰度 < thr 裁到墨边、取左 `left` 宽、反相归一、缩成 size×size，
各网取平均得「候」的概率 p，p ≥ t 给 候、p ≤ 1−t 给 𠋫，其余弃权。训练用 sheldon 点选 222 格＋算法目看一致 134 格，
按册 5 折留出 t=0.98 覆盖 sheldon 标签 193/222、错 1（057:43:5:1，图上是通长第二竖，疑点选错）::

    {"schema": "hou_shape/2", "chars": ["候", "𠋫"], "size": 64, "left": 0.6, "thr": 140, "t": 0.98, "nets": [...]}
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

SCHEMA = "hou_shape/1"
SCHEMA_NET = "hou_shape/2"


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
    if d.get("schema") == SCHEMA_NET:
        from .wu_shape import _arr
        d["_nets"] = [{k: _arr(v) for k, v in n.items()} for n in d["nets"]]
        return d
    if d.get("schema") != SCHEMA:
        raise ValueError(f"hou_shape：{path} 不是 {SCHEMA}／{SCHEMA_NET}")
    if not float(d["lo"]) <= float(d["hi"]):
        raise ValueError(f"hou_shape：{path} 要 lo ≤ hi")
    return d


def load(path: str) -> dict:
    p = Path(path)
    return _load(str(p), p.stat().st_mtime)


def fingerprint(path: str | None) -> str:
    p = Path(path) if path else None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p and p.exists() else ""


def net_input(gray: np.ndarray, size: int = 64, left: float = 0.6, thr: int = 140) -> np.ndarray | None:
    """字块 → 网的输入（左 left 宽、反相 0–1、size×size）；墨太少 → None。"""
    import cv2
    g = np.asarray(gray)
    if g.ndim == 3:
        g = g[..., :3].mean(axis=2)
    g = g.astype(np.float32)
    ys, xs = np.nonzero(g < thr)
    if len(xs) < 50:
        return None
    g = g[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    g = g[:, :max(1, int(g.shape[1] * left))]
    return cv2.resize((255 - g) / 255, (size, size), interpolation=cv2.INTER_AREA)


def judge(gray: np.ndarray, model: dict) -> dict:
    """→ {"char": 候|𠋫|None, "why": "agree"|"abstain:mid"|"abstain:no_ink", "v": 第二竖长 | "p": 候的概率}。"""
    hou, alt = model.get("chars", ["候", "𠋫"])
    if model.get("schema") == SCHEMA_NET:
        from .wu_shape import _forward
        x = net_input(gray, int(model.get("size", 64)), float(model.get("left", 0.6)), int(model.get("thr", 140)))
        if x is None:
            return {"char": None, "why": "abstain:no_ink"}
        pr = float(np.mean([_forward(n, x) for n in model["_nets"]]))
        t = float(model.get("t", 0.98))
        ch = hou if pr >= t else alt if pr <= 1 - t else None
        return {"char": ch, "why": "agree" if ch else "abstain:mid", "p": round(pr, 4)}
    v = second_vertical(gray, int(model.get("thr", 140)))
    if v is None:
        return {"char": None, "why": "abstain:no_ink"}
    ch = hou if v < float(model["lo"]) else alt if v >= float(model["hi"]) else None
    return {"char": ch, "why": "agree" if ch else "abstain:mid", "v": round(v, 4)}


__all__ = ["SCHEMA", "SCHEMA_NET", "second_vertical", "net_input", "load", "fingerprint", "judge"]
