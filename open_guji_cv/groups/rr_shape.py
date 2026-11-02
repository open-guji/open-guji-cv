"""入人八 书级刻形判法（全唐文 995ejelvk0，A24 线 3，2026-11-02，sheldon 定「字形说了算，越过整理本」）。

殿本的 `rr_img`（随机森林）与借来的殿本字形模板在全唐文上把 人 认成 入、八 认成 入/人；全唐文刻得清楚，刻形本身就分得开：

- **八**：两笔断开（≥2 个大连通块），右笔从字顶起（右块 top≈0），左笔起点低（左块 top≥0.2），两块都够长够大；
- **断笔的 人**：也是两块，但反过来——左块顶、右块低，交给下面的分类器；
- **人 / 入**：一笔连着，48px 整字 HOG ＋ 标准化 ＋ 逻辑回归（本书已放行格训，按册留出定门槛）；
- **组外字护栏**：HOG 投到 PCA 空间，离本书训练格最近 5 个的平均距离超过 `guard` → 弃权（挡 尺、爪、乂、切坏的格）。

模型是书级数据（中心库数据目录 `config/groups/rr_shape.json`，`schema: rr_shape/1`），由
`research/char_groups/rr/qtw_shape_train.py` 训练导出；没有这个文件的书本解法不出现，行为不变。
纯 numpy＋cv2 推理，结果确定。
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

SCHEMA = "rr_shape/1"
SIZE = 48
CELL = 8
BINS = 9


def _binarize(gray: np.ndarray) -> np.ndarray | None:
    import cv2
    if gray is None or gray.ndim != 2 or gray.size == 0 or float(gray.std()) < 1.0:
        return None
    g = gray if gray.dtype == np.uint8 else np.clip(gray, 0, 255).astype(np.uint8)
    _, b = cv2.threshold(g, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return b.astype(np.uint8)


def components(gray: np.ndarray):
    """→ (主体二值图 | None, 大块列表 [(top, bottom, left, right, area, cx)])。去碎点（<最大块 8%）与贴边细横线（框线）。"""
    import cv2
    b = _binarize(gray)
    if b is None:
        return None, []
    n, lab, st, cen = cv2.connectedComponentsWithStats(b, connectivity=8)
    if n <= 1:
        return None, []
    amax = st[1:, cv2.CC_STAT_AREA].max()
    H, W = b.shape
    keep = []
    for i in range(1, n):
        x, y, w, h, a = st[i, :5]
        if a < 0.08 * amax:
            continue
        if h <= 0.08 * H and w > 0.3 * W:          # 框线、版心线
            continue
        keep.append((int(y), int(y + h), int(x), int(x + w), int(a), float(cen[i][0]), i))
    if not keep:
        return None, []
    m = np.isin(lab, [k[6] for k in keep])
    ys, xs = np.nonzero(m)
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1], [k[:6] for k in keep]


def geometry(comps) -> dict:
    """两大块的相对位置（以字高归一）。只有一块 → {"n": 1}。"""
    if len(comps) < 2:
        return {"n": len(comps)}
    cs = sorted(comps, key=lambda c: -c[4])
    a, b = cs[0], cs[1]
    left, right = (a, b) if a[5] < b[5] else (b, a)
    top = min(c[0] for c in comps)
    H = max(c[1] for c in comps) - top
    return {"n": len(comps), "ratio": b[4] / a[4],
            "Lh": (left[1] - left[0]) / H, "Rh": (right[1] - right[0]) / H,
            "Ltop": (left[0] - top) / H, "Rtop": (right[0] - top) / H}


def is_ba(g: dict, p: dict) -> bool:
    return (g["n"] >= 2 and g["Rtop"] < p["ba_rtop_max"] and g["Ltop"] >= p["ba_ltop_min"]
            and g["Rh"] >= p["ba_rh_min"] and g["Lh"] >= p["ba_lh_min"] and g["ratio"] >= p["ba_ratio_min"])


def is_broken_ren(g: dict, p: dict) -> bool:
    return g["n"] >= 2 and g["Ltop"] < p["ba_rtop_max"] and g["Rtop"] >= p["ren_rtop_min"]


def _square(m: np.ndarray) -> np.ndarray:
    import cv2
    h, w = m.shape
    s = max(h, w)
    q = np.zeros((s, s), np.float32)
    q[(s - h) // 2:(s - h) // 2 + h, (s - w) // 2:(s - w) // 2 + w] = m
    return cv2.resize(q, (SIZE, SIZE), interpolation=cv2.INTER_AREA)


def hog(m: np.ndarray) -> np.ndarray:
    """48×48 主体图 → 900 维 HOG（8px 格、9 向、2×2 块 L2 归一）。"""
    p = _square(m)
    gy, gx = np.gradient(p)
    mag = np.hypot(gx, gy)
    b = np.minimum(((np.arctan2(gy, gx) % np.pi) / np.pi * BINS).astype(int), BINS - 1)
    n = SIZE // CELL
    cells = np.zeros((n, n, BINS), np.float32)
    for i in range(n):
        for j in range(n):
            sl = (slice(i * CELL, (i + 1) * CELL), slice(j * CELL, (j + 1) * CELL))
            np.add.at(cells[i, j], b[sl].ravel(), mag[sl].ravel())
    out = []
    for i in range(n - 1):
        for j in range(n - 1):
            v = cells[i:i + 2, j:j + 2].ravel()
            out.append(v / np.sqrt(float((v ** 2).sum()) + 1e-4))
    return np.concatenate(out)


def features(gray: np.ndarray):
    """→ (HOG | None, 几何 dict)。"""
    m, comps = components(gray)
    if m is None or m.shape[0] < 8 or m.shape[1] < 4:
        return None, {"n": 0}
    return hog(m), geometry(comps)


@lru_cache(maxsize=4)
def load(path: str) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("schema") != SCHEMA:
        raise ValueError(f"rr_shape：{path} 不是 {SCHEMA}")
    for k in ("mean", "scale", "coef", "pca_mean", "pca", "bank"):
        d[k] = np.asarray(d[k], np.float32)
    return d


def fingerprint(path: str | None) -> str:
    p = Path(path) if path else None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p and p.exists() else ""


def judge(gray: np.ndarray, model: dict) -> dict:
    """→ {"char": 人|入|八|None, "why": …, 量}。"""
    f, g = features(gray)
    if f is None:
        return {"char": None, "why": "abstain:no_ink", "geo": g}
    z = (f - model["pca_mean"]) @ model["pca"].T
    d = np.sqrt(((model["bank"] - z) ** 2).sum(1))
    nn = float(np.sort(d)[:5].mean())
    out = {"geo": {k: round(float(v), 3) for k, v in g.items()}, "nn": round(nn, 3)}
    if nn > model["guard"]:
        return {**out, "char": None, "why": "abstain:out_of_group"}
    p = model["params"]
    if is_ba(g, p):
        return {**out, "char": "八", "why": "agree"}
    if g["n"] >= 2 and not is_broken_ren(g, p):
        return {**out, "char": None, "why": "abstain:geometry"}
    with np.errstate(divide="ignore", invalid="ignore"):
        s = float(((f - model["mean"]) / model["scale"]) @ model["coef"] + model["intercept"])
    if not np.isfinite(s):
        return {**out, "char": None, "why": "abstain:nan"}
    out["score"] = round(s, 3)
    if abs(s) < model["thr"]:
        return {**out, "char": None, "why": "abstain:low_margin"}
    return {**out, "char": "入" if s > 0 else "人", "why": "agree"}
