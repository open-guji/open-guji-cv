"""书级「两字」刻形判法（史记 之／矣，2026-11-03；套路同 `rr_shape`，但不带几何规则，只有 HOG＋逻辑回归＋组外护栏）。

殿本之／矣刻形差得大（矣有厶与矢），形近护栏却因 库首位／整理本 一为之一为矣而把格拦下。本书已放行的之、矣格足够训一个二选一：

- 48px 整字 HOG（沿用 `rr_shape.features`：去碎点、去贴边细横线）＋标准化＋逻辑回归，决策值绝对值 ≥ `thr` 才给字；
- 组外护栏：HOG 投到 PCA 空间，离训练格最近 5 个的平均距离超过 `guard` → 弃权（挡切坏的格、别的字）。

模型是书级数据（中心库数据目录 `config/groups/pair_shape_<两字拼音>.json`，`schema: pair_shape/1`），
训练见 `research/char_groups/pair_shape/train.py`；没有模型的书本解法不出现，行为不变。纯 numpy＋cv2 推理，结果确定。
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from .rr_shape import features

SCHEMA = "pair_shape/1"


@lru_cache(maxsize=8)
def load(path: str) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("schema") != SCHEMA:
        raise ValueError(f"pair_shape：{path} 不是 {SCHEMA}")
    for k in ("mean", "scale", "coef", "pca_mean", "pca", "bank"):
        d[k] = np.asarray(d[k], np.float32)
    return d


def fingerprint(path: str | None) -> str:
    p = Path(path) if path else None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p and p.exists() else ""


def judge(gray: np.ndarray, model: dict) -> dict:
    """→ {"char": chars[0]|chars[1]|None, "why": …, 量}。score>0 给 chars[1]。"""
    f, _g = features(gray)
    if f is None:
        return {"char": None, "why": "abstain:no_ink"}
    z = (f - model["pca_mean"]) @ model["pca"].T
    d = np.sqrt(((model["bank"] - z) ** 2).sum(1))
    nn = float(np.sort(d)[:5].mean())
    out = {"nn": round(nn, 3)}
    if nn > model["guard"]:
        return {**out, "char": None, "why": "abstain:out_of_group"}
    with np.errstate(divide="ignore", invalid="ignore"):
        s = float(((f - model["mean"]) / model["scale"]) @ model["coef"] + model["intercept"])
    if not np.isfinite(s):
        return {**out, "char": None, "why": "abstain:nan"}
    out["score"] = round(s, 3)
    if abs(s) < model["thr"]:
        return {**out, "char": None, "why": "abstain:low_margin"}
    a, b = model["chars"]
    return {**out, "char": b if s > 0 else a, "why": "agree"}
