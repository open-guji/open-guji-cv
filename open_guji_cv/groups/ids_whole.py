"""整字线性判别（`ids_online` 的 `whole` 判法，2026-10-20 呂吕、徵徴）。

按字分类（`by_form`）把字块从缝里切开比一段；呂吕 差在中间连笔、徵徴 差在字中上部的细节，缝两侧没有差别，切开比不了。
这里不切：整字裁墨迹外框、缩成 `size`×`size`，取一块区域（`region`＝占宽高的 x0,x1,y0,y1），
抽特征（`pix`：模糊后缩 16×16 的像素；`hog`：8 像素格、12 向、2×2 块归一的梯度方向直方图），
在冻结模板库（每字的真实刻例）上训**二类岭回归**（目标 ±1，模板就是训练集），判别值绝对值不到 `min_margin` 弃权。

- 两类：单个二类岭回归（呂吕、徵徴）；三类及以上（2026-10-21，山由出）：一对多岭回归，判别值＝第一名与第二名得分之差。
  每类模板少于 `min_class` 个，判成它也弃权。
- 模板库格式同 `ids_online`（`templates={字: [size×size 的 uint8 墨迹图,…]}`），另在 `source.books` 里按模板顺序记所属册，
  供按册留一评测（判某册时模板不含该册）。
- 在线字块与建库的字块都经 `norm`（<128 为墨，裁外框，缩放），所以两边一致。
- 分层 L2：只依赖 numpy、PIL 与同包 `ids_segment`／`ids_parts`。
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from .ids_parts import _blur
from .ids_segment import ink_of

PIX = 16
HOG_CELL = 8
HOG_BINS = 12


def norm(gray: np.ndarray, size: int) -> np.ndarray | None:
    """灰度字块 → 墨迹外框 → 缩成 size×size 的 0–1 墨迹图（不保持宽高比）；无墨迹 → None。"""
    ink = ink_of(gray)
    if not ink.any():
        return None
    ys, xs = np.where(ink)
    crop = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8) * 255
    return np.asarray(Image.fromarray(crop).resize((size, size), Image.BILINEAR), dtype=np.float32) / 255.0


def clean_patch(gray: np.ndarray) -> np.ndarray:
    """去邻格碎墨（2026-10-22，文意组字形第二路）：墨迹 8 连通域里，面积 ≥ 最大块 15% 的算主体；
    其余小块贴边、落在主体外框（外扩 8%）之外、或面积不到最大块 1% 的抹白；主体级的块若贴边、不到最大块 35% 且细长（宽或高 < 12%）
    也抹白（邻列笔画）。线上字块常带邻格碎墨，按墨迹外框归一后整字变形，論→諭、自→目 会高把握判错。cv2 惰性导入。"""
    import cv2
    g = np.asarray(gray)
    ink = ink_of(g).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    if n <= 2:
        return g
    H, W = g.shape[:2]
    areas = st[1:, cv2.CC_STAT_AREA]
    big = areas.max()
    main = {i + 1 for i, a in enumerate(areas) if a >= 0.15 * big}
    xs0 = min(st[i, 0] for i in main)
    ys0 = min(st[i, 1] for i in main)
    xs1 = max(st[i, 0] + st[i, 2] for i in main)
    ys1 = max(st[i, 1] + st[i, 3] for i in main)
    mx, my = 0.08 * W, 0.08 * H
    out = g.copy()
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in st[i])
        touch = x <= 0 or x + w >= W or y <= 0 or y + h >= H
        if i in main:
            drop = touch and a < 0.35 * big and (w < 0.12 * W or h < 0.12 * H)
        else:
            inside = x >= xs0 - mx and x + w <= xs1 + mx and y >= ys0 - my and y + h <= ys1 + my
            drop = touch or not inside or a < 0.01 * big
        if drop:
            out[lab == i] = 255
    return out


def aspect_ok(gray: np.ndarray, rng: tuple) -> bool:
    """字块宽高比在 `rng=(lo, hi)` 内；超出多半是连进了邻字（如夹注两小字并成一块）。空 `rng` 不查。"""
    if not rng:
        return True
    h, w = np.asarray(gray).shape[:2]
    return rng[0] <= w / max(h, 1) <= rng[1]


def _crop(img: np.ndarray, region: tuple) -> np.ndarray:
    n = img.shape[0]
    x0, x1, y0, y1 = region
    return img[int(y0 * n):int(y1 * n), int(x0 * n):int(x1 * n)]


def _block_hog(p: np.ndarray) -> np.ndarray:
    gy, gx = np.gradient(p.astype(np.float32))
    mag = np.hypot(gx, gy)
    b = np.minimum(((np.arctan2(gy, gx) % np.pi) / np.pi * HOG_BINS).astype(int), HOG_BINS - 1)
    n, m = p.shape[0] // HOG_CELL, p.shape[1] // HOG_CELL
    cells = np.zeros((n, m, HOG_BINS), np.float32)
    for i in range(n):
        for j in range(m):
            sl = (slice(i * HOG_CELL, (i + 1) * HOG_CELL), slice(j * HOG_CELL, (j + 1) * HOG_CELL))
            np.add.at(cells[i, j], b[sl].ravel(), mag[sl].ravel())
    out = []
    for i in range(n - 1):
        for j in range(m - 1):
            v = cells[i:i + 2, j:j + 2].ravel()
            out.append(v / np.sqrt(float((v ** 2).sum()) + 1e-4))
    return np.concatenate(out) if out else np.zeros(0, np.float32)


def feature(img: np.ndarray, kind: str, region: tuple) -> np.ndarray:
    """归一整字图 → 特征向量。"""
    p = _blur(_crop(img, region))
    if kind == "pix":
        n = p.shape[0] // PIX
        return p[:n * PIX, :n * PIX].reshape(PIX, n, PIX, n).mean(axis=(1, 3)).ravel() if n else p.ravel()
    if kind == "hog":
        return _block_hog(p)
    raise ValueError(f"整字判法：特征 {kind!r} 不认得")


_CACHE: dict = {}


def fit(bank: dict, kind: str, region: tuple, lam: float):
    """模板库 → `(两个字名, 权重)`；按库对象缓存（库对象常驻内存，持引用保证 id 不复用）。"""
    key = (id(bank), kind, tuple(region), lam)
    hit = _CACHE.get(key)
    if hit is not None and hit[0] is bank:
        return hit[1]
    names = tuple(sorted(n for n, ts in bank.items() if ts))
    if len(names) < 2:
        res = (names, None)
    elif len(names) > 2:
        # 一对多：每类一列权重（目标 ±1），共用同一个 x'x
        xs, lab = [], []
        for n in names:
            for t in bank[n]:
                xs.append(np.r_[feature(t, kind, region), 1.0])
                lab.append(n)
        x = np.array(xs, np.float64)
        reg = lam * np.eye(x.shape[1])
        reg[-1, -1] = 0.0
        tgt = np.array([[1.0 if l == n else -1.0 for n in names] for l in lab])
        res = (names, np.linalg.solve(x.T @ x + reg, x.T @ tgt))
    else:
        xs, ts = [], []
        for sign, n in zip((-1.0, 1.0), names):
            for t in bank[n]:
                xs.append(np.r_[feature(t, kind, region), 1.0])
                ts.append(sign)
        x = np.array(xs, np.float64)
        reg = lam * np.eye(x.shape[1])
        reg[-1, -1] = 0.0
        res = (names, np.linalg.solve(x.T @ x + reg, x.T @ np.array(ts)))
    _CACHE[key] = (bank, res)
    return res


def score(gray: np.ndarray, bank: dict, kind: str, region: tuple, lam: float, size: int):
    """→ `(字, 判别值绝对值, {字: 判别值})`；空白、库不足两类 → `(None, 0.0, {})`。两类：判别值为正偏向名字排序靠后的字；
    三类以上：字＝得分最高的类，判别值＝与第二名的得分差，`{字: 得分}`。"""
    return score_norm(norm(np.asarray(gray), size), bank, kind, region, lam)


def score_norm(x: np.ndarray | None, bank: dict, kind: str, region: tuple, lam: float):
    """同 `score`，输入已是归一整字图（评测直接用模板，不再过 `norm`）。"""
    names, w = fit(bank, kind, region, lam)
    if x is None or w is None:
        return None, 0.0, {}
    f = np.r_[feature(x, kind, region), 1.0]
    if w.ndim == 2:
        sc = f @ w
        o = np.argsort(-sc)
        return names[o[0]], float(sc[o[0]] - sc[o[1]]), {n: float(v) for n, v in zip(names, sc)}
    d = float(f @ w)
    return (names[1] if d > 0 else names[0]), abs(d), {names[0]: -d, names[1]: d}


# —— 离线：建库与按册留一评测（`research/m7/lane1/build_whole_bank.py` 调用） ——

def build(group: str, cells, size: int, source: dict | None = None) -> dict:
    """`cells = [(成员字, 灰度字块, 册, 格 id), …]`（人裁过的真实刻例）→ 模板库 dict；`source.books`／`source.keys` 按模板顺序记册与格。"""
    from .ids_online import dump_bank
    tpl: dict = {}
    books: dict = {}
    keys: dict = {}
    for form, gray, book, key in cells:
        x = norm(np.asarray(gray), size)
        if x is not None:
            tpl.setdefault(form, []).append(x)
            books.setdefault(form, []).append(book)
            keys.setdefault(form, []).append(key)
    return dump_bank(group, tpl, {**(source or {}), "books": {k: books[k] for k in sorted(books)},
                                  "keys": {k: keys[k] for k in sorted(keys)},
                                  "cells": sum(len(v) for v in tpl.values())}, size=size)


def evaluate(group: str, bank_json: dict, margins=(0.3, 0.4, 0.5, 0.6, 0.7)) -> dict:
    """按册留一：判某册的每个模板时，模板库不含该册。→ {门槛: {right, abstain, wrong}}，另附不设门槛的错例。"""
    from .ids_online import SPECS, _dec
    sp = SPECS[group]
    size = int(bank_json["size"])
    tpl = {k: [_dec(s, size) for s in v] for k, v in bank_json["templates"].items()}
    books = bank_json["source"]["books"]
    keys = bank_json["source"]["keys"]
    names = sorted(tpl)
    items = [(f, i, books[f][i]) for f in names for i in range(len(tpl[f]))]
    out = {m: {"right": 0, "abstain": 0, "wrong": 0} for m in margins}
    wrong = []
    for f, i, bk in items:
        sub = {n: [t for j, t in enumerate(tpl[n]) if books[n][j] != bk] for n in names}
        ch, m, _ = score_norm(tpl[f][i], sub, sp.whole, tuple(sp.region), sp.lam)
        for g in margins:
            k = "abstain" if ch is None or m < g else "right" if ch == f else "wrong"
            out[g][k] += 1
        if ch != f:
            wrong.append((f, keys[f][i], ch, round(float(m), 3)))
    return {"by_margin": out, "wrong": wrong, "cells": len(items)}

