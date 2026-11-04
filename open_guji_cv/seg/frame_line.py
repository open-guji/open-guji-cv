"""整页拟合双边版框的内框细线（2026-11-04，Sheldon 定：整页统一认内框，线上的像素统一抹掉）。

## 为什么要整页拟合

殿本（新图源）是双边版框：外面一道粗框，往里十几像素一道细内框。字就写在细内框以内，列首、列尾的字常常
贴着它，甚至笔画压在线上。细内框印得淡、磨成虚线。

以前逐列、逐格判断「这一行像不像线」：要满宽、要有白行把线和字隔开、要不连着字身。线跟字一粘连，这三条
都不成立，碰着字脚的那一截就留在字块里（所、祖、八、父的撇脚，中、謂的竖脚）。

整页看就简单多了。外粗框又粗又满，整页拟得非常稳；内细线跟外框平行，离外框一样远。一张页上几十段
虚线一起投票，哪一段被字遮住、哪一段磨断了都不要紧。定下线位和线厚以后，线带（连同线外）的像素一律抹白，
不再问它连不连着字。

## 怎么拟

1. 在版框提示 y 附近的横带里，把文字块宽切成 CHUNK 像素宽的小段，每段算行墨占比，取墨占比 ≥ RUN_COV 的
   连续行段；
2. **外粗框**：每段里最厚（≥ OUTER_MIN_THICK 行）的行段，取它朝页心那一边，RANSAC 拟二次曲线
   （纸张微弯，允许一点弯度）；
3. **内细线**：外框朝页心一侧 INNER_MAX_GAP 格高以内、厚 1–INNER_MAX_THICK 行的薄段，量它离外框多远；
   离外框的距离按 x 的一次式 RANSAC 拟（两道线基本平行，最多差一点斜率），线心＝外框曲线减这个距离；
4. 质量：外框内点占小段的比例、内线有支持的小段比例，太低就认为本页没有可信的内框，返回 None。

纯看图、量东西：坐标是传进来那张图的像素坐标（x 向右、y 向下），不认识任何一套书。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

CHUNK = 12               # 小段宽（px）：比虚线的段长短，比笔画宽
RUN_COV = 0.5            # 小段内一行有这么多墨算「这行在线上」
OUTER_MIN_THICK = 5      # 外粗框的行段至少这么厚（新图源外框 7–10 行、内线 3–4 行）
INNER_MAX_THICK = 7      # 内细线的行段至多这么厚
INNER_MAX_GAP = 0.4      # 内细线离外框最多这么多格高
OUTER_TOL = 2.0          # 外框 RANSAC 内点容差（px）
INNER_TOL = 1.5          # 内线距离 RANSAC 内点容差（px）
INNER_MAX_SLOPE = 0.01   # 内线距外框的距离随 x 的斜率上限（基本平行）
MIN_OUTER_INLIER = 0.35  # 外框内点至少占小段这么多
MIN_INNER_SUPPORT = 0.2  # 内线至少在这么多小段上看得见
GAP_MAX_INK = 0.15       # 内线与外框之间那条白缝：各小段墨占比的中位数不过这么多
GAP_MIN_ROWS = 2         # 白缝至少这么多行
BLANK_ABOVE = 0.6        # 线朝页心这么多格高里几乎没墨的小段（行间空白、空格下）算「空段」
BLANK_INK = 0.01         # ……墨占比不过这么多
MIN_BLANK_HITS = 0.35    # 空段里至少这么多段看得见内线（末行字的底横只在字下，空段里没有）
MIN_BLANK_N = 5          # 空段不到这么多就不验
RANSAC_ITERS = 300


@dataclass(frozen=True)
class InnerFrameLine:
    """内框细线：线心 y(x) ＝ np.polyval(center, x)，线厚 thick（px）。"""
    side: str                    # "bottom" | "top"
    center: tuple[float, ...]    # 二次多项式系数（高次在前）
    thick: float
    outer_inlier: float          # 外框拟合内点比例
    support: float               # 内线有支持的小段比例
    x_range: tuple[int, int]

    def y(self, x) -> np.ndarray:
        return np.polyval(np.asarray(self.center, float), np.asarray(x, float))

    def text_edge(self, x) -> np.ndarray:
        """线朝页心（字那边）的边沿 y：下框线取上沿，上框线取下沿。"""
        h = self.thick / 2.0
        return self.y(x) - h if self.side == "bottom" else self.y(x) + h


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    i, n = 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def _ransac_poly(x: np.ndarray, y: np.ndarray, deg: int, tol: float, rng: np.random.Generator,
                 max_slope: float | None = None) -> np.ndarray | None:
    best = None
    k = deg + 1
    if len(x) < k:
        return None
    for _ in range(RANSAC_ITERS):
        idx = rng.choice(len(x), k, replace=False)
        if len(set(x[idx].tolist())) < k:
            continue
        c = np.polyfit(x[idx], y[idx], deg)
        if max_slope is not None and deg == 1 and abs(c[0]) > max_slope:
            continue
        inl = np.abs(y - np.polyval(c, x)) <= tol
        if best is None or inl.sum() > best.sum():
            best = inl
    return best


def fit_inner_frame_line(ink: np.ndarray, x0: int, x1: int, y_hint: float, cell_h: float,
                         side: str = "bottom", seed: int = 0) -> InnerFrameLine | None:
    """在二值墨图 `ink`（True＝墨）上拟一道内框细线。

    x0/x1：文字块左右（只在这段里量）；y_hint：版框大致的 y（Step1/2 给的，内线或外框都行）；
    cell_h：格高（定搜索带与距离上限）；side：下框 "bottom" / 上框 "top"。拟不出可信的线返回 None。"""
    h, w = ink.shape
    x0, x1 = max(0, int(x0)), min(w, int(x1))
    if side == "bottom":
        lo, hi = int(y_hint - 0.5 * cell_h), int(y_hint + 0.4 * cell_h)
    else:
        lo, hi = int(y_hint - 0.4 * cell_h), int(y_hint + 0.5 * cell_h)
    lo, hi = max(0, lo), min(h, hi)
    if x1 - x0 < 4 * CHUNK or hi - lo < 8:
        return None
    band = ink[lo:hi]
    chunks: list[tuple[float, list[tuple[int, int]]]] = []
    ox, oy = [], []
    for x in range(x0, x1 - CHUNK + 1, CHUNK):
        rr = [(s + lo, t + lo) for s, t in _runs(band[:, x:x + CHUNK].mean(axis=1) >= RUN_COV)]
        cx = x + CHUNK / 2.0
        chunks.append((cx, rr))
        thick = [r for r in rr if r[1] - r[0] >= OUTER_MIN_THICK]
        if thick:
            r = max(thick, key=lambda r: r[1] - r[0])
            ox.append(cx)
            oy.append(r[0] if side == "bottom" else r[1])     # 外框朝页心那一边
    if len(ox) < 8:
        return None
    rng = np.random.default_rng(seed)
    ox_a, oy_a = np.asarray(ox, float), np.asarray(oy, float)
    inl = _ransac_poly(ox_a, oy_a, 2, OUTER_TOL, rng)
    if inl is None or inl.sum() < MIN_OUTER_INLIER * len(chunks):
        return None
    outer = np.polyfit(ox_a[inl], oy_a[inl], 2)
    sign = 1.0 if side == "bottom" else -1.0         # 距离朝页心为正
    cx_l, d_l, t_l = [], [], []
    for cx, rr in chunks:
        o = float(np.polyval(outer, cx))
        for s, t in rr:
            d = (o - t) if side == "bottom" else (s - o)
            if 1 <= d <= INNER_MAX_GAP * cell_h and 1 <= t - s <= INNER_MAX_THICK:
                cx_l.append(cx)
                d_l.append(sign * (o - (s + t) / 2.0))      # 线心离外框的距离（朝页心为正）
                t_l.append(t - s)
    if len(cx_l) < 6:
        return None
    cx_a, d_a, t_a = np.asarray(cx_l, float), np.asarray(d_l, float), np.asarray(t_l, float)
    inl2 = _ransac_poly(cx_a, d_a, 1, INNER_TOL, rng, max_slope=INNER_MAX_SLOPE)
    if inl2 is None:
        return None
    support = len({float(v) for v in cx_a[inl2]}) / len(chunks)
    if support < MIN_INNER_SUPPORT:
        return None
    k, b = np.polyfit(cx_a[inl2], d_a[inl2], 1)
    center = np.asarray(outer, float).copy()
    center[1] -= sign * k
    center[2] -= sign * b
    thick = float(np.median(t_a[inl2]))
    # 内线与外框之间要隔着一条白缝。末行字的底横常落在差不多同一高度、也离外框十几行，拟线拟到字脚上时，
    # 它和外框之间夹着真正的内线（贴着外框、跟外框粘成一条粗段时认不出来），缝就不白
    fr = []
    for cx, _rr in chunks:
        o = float(np.polyval(outer, cx))
        c = float(np.polyval(center, cx))
        a, z = (int(np.ceil(c + thick / 2.0)) + 1, int(np.floor(o)) - 1) if side == "bottom" else \
            (int(np.ceil(o)) + 1, int(np.floor(c - thick / 2.0)) - 1)
        if z - a + 1 < GAP_MIN_ROWS:
            return None
        xi = int(cx - CHUNK / 2.0)
        fr.append(float(ink[max(0, a):min(h, z + 1), xi:xi + CHUNK].mean()))
    if not fr or float(np.median(fr)) > GAP_MAX_INK:
        return None
    # 真内线是整页横贯的，字与字之间、空格底下也有；末行字的底横只在字下。看「上面没字」的小段里线在不在
    hit_x = {float(v) for v in cx_a[inl2]}
    n_blank = n_hit = 0
    for cx, _rr in chunks:
        c = float(np.polyval(center, cx))
        a, z = (int(c - thick / 2.0 - BLANK_ABOVE * cell_h), int(c - thick / 2.0) - 2) if side == "bottom" else \
            (int(c + thick / 2.0) + 3, int(c + thick / 2.0 + BLANK_ABOVE * cell_h))
        xi = int(cx - CHUNK / 2.0)
        sub = ink[max(0, a):min(h, z + 1), xi:xi + CHUNK]
        if sub.size and float(sub.mean()) <= BLANK_INK:
            n_blank += 1
            n_hit += cx in hit_x
    if n_blank >= MIN_BLANK_N and n_hit < MIN_BLANK_HITS * n_blank:
        return None
    return InnerFrameLine(side=side, center=tuple(float(v) for v in center),
                          thick=thick, outer_inlier=float(inl.mean()),
                          support=float(support), x_range=(x0, x1))
