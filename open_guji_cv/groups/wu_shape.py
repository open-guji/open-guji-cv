"""嗚鳴 书级刻形判法（全唐文 995ejelvk0，形近字线 2026-11-14；sheldon 11-13 定「归形近不同义组，拆部件 100% 自动区分」，
11-14 嗚鳴17格按刻形点：嗚呼刻成 鳴 的格记 鳴）。

烏 与 鳥 只差右上方框里中间那一横（烏 没有）。取字块口旁右边那一半的上 75%，缩成 64×64，交三个小卷积网
（3 层 3×3 卷积＋池化、两层全连接，训练见 ai-team 形近字线笔记）取平均：p 是「鳴」的概率，p ≥ t 给 鳴、p ≤ 1−t 给 嗚，
其余弃权。按册 5 折留出 1,199 格（文意放行 1,183＋Sheldon 17 格刻形点选），t=0.99 覆盖约 98%、0 错。

前向用 numpy 算（管线不依赖 torch），权重存 JSON（float16 base64），一本书一份，随中心库走（`config/groups/wu_shape.json`）::

    {"schema": "wu_shape/1", "chars": ["嗚", "鳴"], "size": 64, "top": 0.75, "t": 0.99,
     "nets": [{"f.0.weight": {"shape": [...], "dtype": "<f2", "b64": "..."}, ...}, ...]}
"""
from __future__ import annotations

import base64
import hashlib
import json
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

SCHEMA = "wu_shape/1"
_CONVS = ("f.0", "f.3", "f.6")
_FCS = ("f.11", "f.13")


def _binarize(gray: np.ndarray) -> np.ndarray:
    g = cv2.GaussianBlur(gray, (3, 3), 0)
    _, b = cv2.threshold(g, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b.astype(np.uint8), 8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, 4] >= max(8, b.sum() * 0.004)
    return keep[lab].astype(np.uint8)


def right_part(gray: np.ndarray) -> np.ndarray | None:
    """字块 → 口旁右边那一半（二值，裁到墨边）；墨太少 → None。口旁与右半的分界取 0.2–0.5 宽里竖向墨量（3 点平滑）最少的列。"""
    b = _binarize(gray)
    ys, xs = np.nonzero(b)
    if len(xs) < 50:
        return None
    b = b[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    W = b.shape[1]
    a, z = int(.2 * W), int(.5 * W)
    if z - a < 3:
        return None
    colsum = b.sum(0).astype(float)
    sx = a + int(np.argmin(np.convolve(colsum[a:z], np.ones(3) / 3, "same")))
    r = b[:, sx:]
    rxs = np.nonzero(r)[1]
    if len(rxs) < 20:
        return None
    return r[:, rxs.min():]


def prep(gray: np.ndarray, size: int = 64, top: float = 0.75) -> np.ndarray | None:
    r = right_part(gray)
    if r is None:
        return None
    r = r[:max(1, int(top * r.shape[0]))].astype(np.float32)
    return cv2.resize(r, (size, size), interpolation=cv2.INTER_AREA)


def _arr(d: dict) -> np.ndarray:
    a = np.frombuffer(base64.b64decode(d["b64"]), dtype=d.get("dtype", "<f4"))
    return a.astype(np.float32).reshape(d["shape"])


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("schema") != SCHEMA:
        raise ValueError(f"wu_shape：{path} 不是 {SCHEMA}")
    d["_nets"] = [{k: _arr(v) for k, v in n.items()} for n in d["nets"]]
    return d


def load(path: str) -> dict:
    p = Path(path)
    return _load(str(p), p.stat().st_mtime)


def fingerprint(path: str | None) -> str:
    p = Path(path) if path else None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p and p.exists() else ""


def _conv3(x: np.ndarray, w: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(C,H,W) 3×3 卷积、补零 1 → (O,H,W)。"""
    C, H, W = x.shape
    xp = np.pad(x, ((0, 0), (1, 1), (1, 1)))
    cols = np.lib.stride_tricks.sliding_window_view(xp, (3, 3), axis=(1, 2))   # C,H,W,3,3
    cols = cols.transpose(1, 2, 0, 3, 4).reshape(H * W, C * 9)
    return (cols @ w.reshape(w.shape[0], -1).T + b).T.reshape(w.shape[0], H, W)


def _pool2(x: np.ndarray) -> np.ndarray:
    C, H, W = x.shape
    return x[:, :H // 2 * 2, :W // 2 * 2].reshape(C, H // 2, 2, W // 2, 2).max((2, 4))


def _forward(net: dict, x: np.ndarray) -> float:
    h = x[None]
    for k in _CONVS:
        h = _pool2(np.maximum(_conv3(h, net[k + ".weight"], net[k + ".bias"]), 0))
    h = h.reshape(-1)
    h = np.maximum(net[_FCS[0] + ".weight"] @ h + net[_FCS[0] + ".bias"], 0)
    z = float((net[_FCS[1] + ".weight"] @ h + net[_FCS[1] + ".bias"]).reshape(-1)[0])
    return 1.0 / (1.0 + np.exp(-z))


def prob(gray: np.ndarray, model: dict) -> float | None:
    """「鳴」的概率（各网平均）；字块取不出右半 → None。"""
    x = prep(gray, int(model.get("size", 64)), float(model.get("top", 0.75)))
    if x is None:
        return None
    return float(np.mean([_forward(n, x) for n in model["_nets"]]))


def judge(gray: np.ndarray, model: dict) -> dict:
    """→ {"char": 嗚|鳴|None, "why": "agree"|"abstain:low_p"|"abstain:no_ink", "p": 鳴 概率}。"""
    p = prob(gray, model)
    if p is None:
        return {"char": None, "why": "abstain:no_ink"}
    t = float(model.get("t", 0.99))
    wu, ming = model.get("chars", ["嗚", "鳴"])
    ch = ming if p >= t else wu if p <= 1 - t else None
    return {"char": ch, "why": "agree" if ch else "abstain:low_p", "p": round(p, 4)}


__all__ = ["SCHEMA", "prep", "load", "fingerprint", "prob", "judge"]
