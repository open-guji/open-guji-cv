"""书级「两字」刻形判法（史记 之／矣，2026-11-03；套路同 `rr_shape`，但不带几何规则，只有 HOG＋逻辑回归＋组外护栏）。

殿本之／矣刻形差得大（矣有厶与矢），形近护栏却因 库首位／整理本 一为之一为矣而把格拦下。本书已放行的之、矣格足够训一个二选一：

- 48px 整字 HOG（沿用 `rr_shape.features`：去碎点、去贴边细横线）＋标准化＋逻辑回归，决策值绝对值 ≥ `thr` 才给字；
- 组外护栏：HOG 投到 PCA 空间，离训练格最近 5 个的平均距离超过 `guard` → 弃权（挡切坏的格、别的字）。

`pair_shape/2`（全唐文 大太／王玉／還遺，2026-11-07）：区别只在一个点（太、玉）时 HOG 不行（按册留出错 278／183），
改用主笔画紧框 32×32 墨量图（`pix_ink`／`pix_features`）＋逻辑回归，再加一个「本组 vs 组外形近字」判别当组外护栏
（`other`，分值 ≥ `other_thr` 弃权）；`veto_thr` 给 seed_admit 的 `group_flow_pair_shape_veto` 用。训练见
`research/char_groups/pair_shape/train_pix.py`。

模型是书级数据（中心库数据目录 `config/groups/pair_shape_<两字拼音>.json`，`schema: pair_shape/1` 或 `/2`），
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
SCHEMA_PIX = "pair_shape/2"      # 墨量图特征＋组外判别（全唐文 大太／王玉／還遺，2026-11-07）


@lru_cache(maxsize=8)
def load(path: str) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("schema") == SCHEMA_PIX:
        for part in ("ab", "other"):
            if d.get(part):
                d[part] = {k: (np.asarray(v, np.float32) if isinstance(v, list) else float(v)) for k, v in d[part].items()}
        return d
    if d.get("schema") != SCHEMA:
        raise ValueError(f"pair_shape：{path} 不是 {SCHEMA}／{SCHEMA_PIX}")
    for k in ("mean", "scale", "coef", "pca_mean", "pca", "bank"):
        d[k] = np.asarray(d[k], np.float32)
    return d


def pix_ink(gray: np.ndarray):
    """→ 主笔画紧框里的二值墨图（uint8 0/1）或 None。

    HOG 在 大太、王玉 上抓不住「那一点」（按册留出错 278／183）：方向直方图按块池化，一个小点只占一格的一点权重。
    这里不池化：Otsu 二值、去碎点（<15px 或 <0.4% 墨量）、去贴边小块与贴左右边的竖线（界行／邻列笔画），
    按主笔画（≥8% 墨量的连通块）取紧框——点、短撇不参与定框，所以框只随字身走，点在框里的位置稳定。"""
    import cv2
    if gray is None or gray.size == 0:
        return None
    g = gray if gray.ndim == 2 else cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    if n <= 1:
        return None
    tot = int(st[1:, 4].sum())
    H, W = b.shape
    keep = np.zeros(b.shape, np.uint8)
    main = np.zeros(b.shape, np.uint8)
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in st[i])
        if a < max(15, 0.004 * tot):
            continue
        if (x == 0 or y == 0 or x + w >= W or y + h >= H) and a < 0.03 * tot:
            continue
        if (x <= 1 or x + w >= W - 1) and h > 3 * w and w < 0.12 * W:
            continue
        keep[lab == i] = 1
        if a >= 0.08 * tot:
            main[lab == i] = 1
    ys, xs = np.nonzero(main)
    if len(xs) == 0:
        return None
    return keep[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def pix_features(ink: np.ndarray, size: int = 32) -> np.ndarray:
    """紧框墨图 → size×size 墨量（INTER_AREA 缩放，0–1），展平。"""
    import cv2
    return cv2.resize(ink.astype(np.float32), (size, size), interpolation=cv2.INTER_AREA).ravel()


def _lr(part: dict, x: np.ndarray) -> float:
    with np.errstate(divide="ignore", invalid="ignore"):
        return float(((x - part["mu"]) / part["sd"]) @ part["coef"] + part["b"])


def judge_pix(gray: np.ndarray, model: dict) -> dict:
    """`pair_shape/2`：→ {"char", "why", "score", "other"}。score>0 给 chars[1]；other＝组外判别分（>门槛＝像组外字）。"""
    ink = pix_ink(gray)
    if ink is None or ink.shape[0] < 6 or ink.shape[1] < 6:
        return {"char": None, "why": "abstain:no_ink"}
    x = pix_features(ink, int(model.get("size", 32)))
    s = _lr(model["ab"], x)
    if not np.isfinite(s):
        return {"char": None, "why": "abstain:nan"}
    out = {"score": round(s, 3)}
    if model.get("other"):
        o = _lr(model["other"], x)
        out["other"] = round(o, 3)
        if not np.isfinite(o) or o >= model["other_thr"]:
            return {**out, "char": None, "why": "abstain:out_of_group"}
    if abs(s) < model["thr"]:
        return {**out, "char": None, "why": "abstain:low_margin"}
    a, b = model["chars"]
    return {**out, "char": b if s > 0 else a, "why": "agree"}


def fingerprint(path: str | None) -> str:
    p = Path(path) if path else None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p and p.exists() else ""


def judge(gray: np.ndarray, model: dict) -> dict:
    """→ {"char": chars[0]|chars[1]|None, "why": …, 量}。score>0 给 chars[1]。"""
    if model.get("schema") == SCHEMA_PIX:
        return judge_pix(gray, model)
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
