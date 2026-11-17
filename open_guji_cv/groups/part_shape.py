"""书级「部件刻形」判法（全唐文 995ejelvk0，码位线 2026-11-15；`wu_shape`（嗚鳴）的泛化）。

一对形近字，差别只在字的某一块部件（剌／刺 左半、疎／踈 左上、攢／攅 …）。字块二值化、裁到墨边，
按 `box`＝(x0, x1, y0, y1)（占墨边宽高的比例）截出部件，缩成 size×size，交几个小卷积网取平均：
p 是 `chars[1]` 的概率，p ≥ t 给 chars[1]，p ≤ 1−t 给 chars[0]，其余弃权。一个模型文件可挂多对，每对自带 box／t／网。
前向与 `wu_shape` 共用（numpy，管线不依赖 torch）；权重存 JSON（float16 base64），一本书一份，随中心库走
（`config/groups/part_shape.json`，参数 `seed_admit.group_flow_part_shape` 显式写才跑，不自动找）::

    {"schema": "part_shape/1", "pairs": [
       {"chars": ["剌", "刺"], "box": [0, 0.65, 0, 1], "size": 64, "t": 0.95,
        "nets": [{"f.0.weight": {"shape": [...], "dtype": "<f2", "b64": "..."}, ...}, ...]}]}
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from .wu_shape import _arr, _binarize, _forward

SCHEMA = "part_shape/1"


def prep(gray: np.ndarray, box, size: int = 64) -> np.ndarray | None:
    """字块 → 部件（二值，缩成 size×size）；墨太少 → None。box＝(x0, x1, y0, y1) 占墨边宽高的比例。"""
    b = _binarize(gray)
    ys, xs = np.nonzero(b)
    if len(xs) < 50:
        return None
    b = b[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.float32)
    H, W = b.shape
    x0, x1, y0, y1 = box
    part = b[int(y0 * H):max(int(y0 * H) + 1, int(y1 * H)), int(x0 * W):max(int(x0 * W) + 1, int(x1 * W))]
    if part.sum() < 20:
        return None
    return cv2.resize(part, (size, size), interpolation=cv2.INTER_AREA)


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("schema") != SCHEMA:
        raise ValueError(f"part_shape：{path} 不是 {SCHEMA}")
    for pr in d["pairs"]:
        pr["_nets"] = [{k: _arr(v) for k, v in n.items()} for n in pr["nets"]]
    d["_chars"] = frozenset(c for pr in d["pairs"] for c in pr["chars"])
    return d


def load(path: str) -> dict:
    p = Path(path)
    return _load(str(p), p.stat().st_mtime)


def fingerprint(path: str | None) -> str:
    p = Path(path) if path else None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p and p.exists() else ""


def pair_of(model: dict, char: str) -> dict | None:
    for pr in model["pairs"]:
        if char in pr["chars"]:
            return pr
    return None


def prob(gray: np.ndarray, pair: dict) -> float | None:
    """`chars[1]` 的概率（各网平均）；字块取不出部件 → None。"""
    x = prep(gray, pair["box"], int(pair.get("size", 64)))
    if x is None:
        return None
    return float(np.mean([_forward(n, x) for n in pair["_nets"]]))


def judge(gray: np.ndarray, pair: dict) -> dict:
    """→ {"char": chars[0]|chars[1]|None, "why": "agree"|"abstain:low_p"|"abstain:no_ink", "p": chars[1] 的概率, "pair": "剌刺"}。"""
    a, b = pair["chars"]
    p = prob(gray, pair)
    if p is None:
        return {"char": None, "why": "abstain:no_ink", "pair": a + b}
    t = float(pair.get("t", 0.99))
    ch = b if p >= t else a if p <= 1 - t else None
    return {"char": ch, "why": "agree" if ch else "abstain:low_p", "p": round(p, 4), "pair": a + b}


__all__ = ["SCHEMA", "prep", "load", "fingerprint", "pair_of", "prob", "judge"]
