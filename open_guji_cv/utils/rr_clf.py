# -*- coding: utf-8 -*-
"""入 / 人 / 八 字形分类器（overview#442 Z-rr 研究版的管线内定型，#437 Z-jys 接线）。

字形有区别（用户 10-06）：「入」撇捺连着且上头有一横；「八」上面也有一横但与左撇不连；「人」连写、上头没有横。
特征：二值化 → 去碎点取主体 → 24×24 网格 ＋ 行列投影 ＋ 顶部带结构（共 24*24+24+24+7 维）。
模型：RandomForest 4 类（人入八＋其他），离线训练（`research/char_groups/rr/export_forest.py`），导出成 npz，这里用 numpy 推理——
管线不依赖 sklearn，结果确定。质量闸：贴边长线、散斑、贴边墨多 → 不给字。

只作证据：给字（p≥阈值、质量闸过、非「其他」）与放行字相左 → 送审（`seed_admit.rr_clf`）；不单独改字、不单独放行。
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import numpy as np

CLASSES = "人入八"
LABELS = ("人", "入", "八", "其他")
N = 24
MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / "rr_clf"


def _cv2():
    import cv2
    return cv2


def binarize(gray: np.ndarray) -> np.ndarray | None:
    cv2 = _cv2()
    if gray is None or gray.ndim != 2 or gray.size == 0:
        return None
    g = cv2.GaussianBlur(gray, (3, 3), 0)
    _, b = cv2.threshold(g, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return b.astype(np.uint8)


def main_body(b: np.ndarray):
    cv2 = _cv2()
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    if n <= 1:
        return None, 0
    areas = st[1:, cv2.CC_STAT_AREA]
    keep = [i + 1 for i, a in enumerate(areas) if a >= 0.08 * areas.max()]
    m = np.isin(lab, keep).astype(np.uint8)
    ys, xs = np.where(m)
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1], len(keep)


def features(gray: np.ndarray) -> np.ndarray | None:
    """→ 特征向量（float32，长 24*24+24+24+7）| None（没有可用的字形）。与研究版 `feat.features` 逐位一致。"""
    cv2 = _cv2()
    b = binarize(gray)
    if b is None:
        return None
    m, ncc = main_body(b)
    if m is None or m.shape[0] < 8 or m.shape[1] < 8:
        return None
    h, w = m.shape
    img = cv2.resize(m.astype(np.float32), (N, N), interpolation=cv2.INTER_AREA)
    rowp = img.sum(1) / N
    colp = img.sum(0) / N
    top = img[: N // 3]
    tcols = np.where(top.sum(0) > 0.25)[0]
    tleft = tcols.min() / N if len(tcols) else 1.0
    tright = tcols.max() / N if len(tcols) else 0.0
    tw = tright - tleft
    tb = (m[: max(2, h // 3)] > 0).astype(np.uint8)
    ntop = cv2.connectedComponents(tb, connectivity=8)[0] - 1
    hand = np.array([h / w, ncc, ntop, tleft, tright, tw, top.sum() / (N * N / 3)], np.float32)
    return np.concatenate([img.ravel(), rowp, colp, hand]).astype(np.float32)


def quality(gray: np.ndarray) -> dict | None:
    """质量闸的三个量（研究版 `clf2.quality`）。"""
    cv2 = _cv2()
    b = binarize(gray)
    if b is None:
        return None
    h, w = b.shape
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    if n <= 1:
        return dict(noise=1.0, line=1, edge=1.0)
    areas = st[1:, cv2.CC_STAT_AREA]
    tot = areas.sum()
    main = areas.max()
    keep = [i + 1 for i, a in enumerate(areas) if a >= 0.08 * main]
    kept = areas[[k - 1 for k in keep]].sum()
    line = 0
    for i in range(1, n):
        x, y, cw, ch, a = st[i]
        touches = x == 0 or y == 0 or x + cw == w or y + ch == h
        if touches and a >= 0.02 * main and (max(cw, ch) / max(1, min(cw, ch)) >= 6):
            line = 1
    edge = float((b[:3].sum() + b[-3:].sum() + b[:, :3].sum() + b[:, -3:].sum())) / max(1, b.sum())
    return dict(noise=1 - kept / tot, line=line, edge=edge)


def gated(q: dict | None, noise_thr: float = 0.12, edge_thr: float = 0.12) -> bool:
    return q is None or q["line"] == 1 or q["noise"] > noise_thr or q["edge"] > edge_thr


class Forest:
    """sklearn RandomForestClassifier 的 numpy 版（只推理）：各树的节点数组拼成一维，`roots` 记每棵树的起点。"""

    def __init__(self, left, right, feat, thr, value, roots):
        self.left, self.right, self.feat, self.thr, self.value, self.roots = left, right, feat, thr, value, roots

    @classmethod
    def load(cls, path) -> "Forest":
        z = np.load(path)
        return cls(z["left"], z["right"], z["feat"], z["thr"], z["value"], z["roots"])

    def proba(self, X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(np.asarray(X, np.float32))
        out = np.zeros((len(X), self.value.shape[1]), np.float64)
        for k, x in enumerate(X):
            for r in self.roots:
                i = int(r)
                while self.left[i] >= 0:
                    i = int(self.left[i] if x[self.feat[i]] <= self.thr[i] else self.right[i])
                out[k] += self.value[i]
        return out / len(self.roots)


def export_forest(model, path) -> None:
    """离线用：把 sklearn 森林写成 npz（叶子存概率；sklearn 的 threshold 是 float64，这里也存 float64 以保证分支逐位一致）。"""
    lefts, rights, feats, thrs, vals, roots, off = [], [], [], [], [], [], 0
    for est in model.estimators_:
        t = est.tree_
        roots.append(off)
        l = t.children_left.copy(); r = t.children_right.copy()
        lefts.append(np.where(l >= 0, l + off, -1)); rights.append(np.where(r >= 0, r + off, -1))
        feats.append(t.feature.copy()); thrs.append(t.threshold.copy())
        v = t.value[:, 0, :]; v = v / v.sum(1, keepdims=True)
        vals.append(v)
        off += t.node_count
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, left=np.concatenate(lefts).astype(np.int32), right=np.concatenate(rights).astype(np.int32),
                        feat=np.concatenate(feats).astype(np.int32), thr=np.concatenate(thrs).astype(np.float64),
                        value=np.concatenate(vals).astype(np.float32), roots=np.array(roots, np.int32))


@lru_cache(maxsize=2)
def _model(path: str) -> Forest:
    return Forest.load(path)


def model_fingerprint(path=None) -> str:
    p = Path(path) if path else MODEL_DIR / "forest.npz"
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else ""


def classify(gray: np.ndarray, model_path=None, p_thr: float = 0.5) -> dict:
    """→ {"probs": {人,入,八,其他}, "pick": 人|入|八|None, "gated": bool, "p": 最大概率}。
    pick=None：没特征、质量闸不过、判为「其他」或最大概率 < p_thr（都是弃权）。"""
    q = quality(gray)
    f = features(gray)
    if f is None:
        return {"probs": None, "pick": None, "gated": True, "p": 0.0}
    P = _model(str(model_path or MODEL_DIR / "forest.npz")).proba(f)[0]
    gate = gated(q)
    k = int(P.argmax())
    pick = LABELS[k] if (k < 3 and P.max() >= p_thr and not gate) else None
    return {"probs": {c: round(float(P[i]), 3) for i, c in enumerate(LABELS)}, "pick": pick, "gated": bool(gate), "p": round(float(P.max()), 3)}
