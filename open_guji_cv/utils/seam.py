# -*- coding: utf-8 -*-
"""折线切分：在直线切点附近的横向走廊里找"最小墨量缝"（seam carving 的横向版）。

用户 2026-09-05 标到 400 条粘连切点后的观察：「对相当多的情况，寻找一条折线的无墨点的
路线是最优解。」实验（`doc/step3_touching_and_jiazhu.md` §1.4）：人标为"重叠·折中"的
205 条里 183 条（89%）在 ±12px 走廊内存在一条完全无墨的折线，缝偏离直线中位 3px。

文献：Saabni & El-Sana 2011、Arvanitopoulos & Süsstrunk 2014 用同一思路切历史手稿文本行。

**它是直线切点之上的一步精修，不替代弹性 DP**：走廊由 DP 给的格线定，缝只在走廊里走。
DP 决定"哪两个字之间"，缝决定"这两个字之间怎么绕"。
"""
from __future__ import annotations

import numpy as np

SEAM_BAND = 12      # 走廊半宽（px）；实验里 p90 偏离 9px，12 够用且不会绕进邻字身
SEAM_STEP = 2       # 每前进一列纵向最多移动的像素
SEAM_TURN = 0.02    # 每 1px 纵向移动的代价（一个墨像素 = 1）
SEAM_MAX_INK = 3    # 缝上墨像素超过这个数就不用缝（保持直线切点）。60 页验收：缝上墨 0 / 1–3 px 的
                    # 相邻字位人审率 1.99% / 1.92%，4–10 px 的 4.40%——绕不开的缝多半在切自己的笔画


def find_seam(ink: np.ndarray, y_c: int, band: int = SEAM_BAND, step: int = SEAM_STEP,
              turn: float = SEAM_TURN) -> np.ndarray:
    """ink: HxW 二值（True/1 = 墨）。返回长度 W 的整型数组：每列 x 上缝所在的行 y。

    走廊 [y_c-band, y_c+band]∩[0,H)。代价 = 路径上的墨像素数 + turn × 纵向总移动量，
    再加一个极小的"离直线远"的惩罚做平局裁决（无墨时贴着直线走，别乱绕）。
    DP 按列推进，纵向候选偏移 -step..+step，numpy 向量化（一列一次）。
    """
    ink = np.asarray(ink)
    h, w = ink.shape
    if w == 0 or h == 0:
        return np.full(w, y_c, dtype=int)
    lo, hi = max(0, y_c - band), min(h - 1, y_c + band)
    n = hi - lo + 1
    rows = np.arange(lo, hi + 1)
    tie = 1e-4 * np.abs(rows - y_c)                      # 平局：靠近直线
    col = ink[lo:hi + 1, :].astype(np.float64)
    cost = col[:, 0] + tie
    back = np.zeros((w, n), dtype=np.int16)
    offsets = np.arange(-step, step + 1)
    for x in range(1, w):
        # 对每个偏移 d，把上一列的代价平移 d 行；越界填 inf
        cand = np.full((len(offsets), n), np.inf)
        for i, d in enumerate(offsets):
            if d >= 0:
                cand[i, d:] = cost[:n - d] + turn * d
            else:
                cand[i, :n + d] = cost[-d:] + turn * (-d)
        best_i = np.argmin(cand, axis=0)
        cost = cand[best_i, np.arange(n)] + col[:, x] + tie
        back[x] = offsets[best_i]
    j = int(np.argmin(cost))
    seam = np.empty(w, dtype=int)
    for x in range(w - 1, -1, -1):
        seam[x] = j + lo
        j -= int(back[x, j])
    return seam


def seam_ink(ink: np.ndarray, seam: np.ndarray) -> int:
    """缝上有多少墨像素（0 = 完全无墨）。"""
    xs = np.arange(len(seam))
    return int(np.asarray(ink)[seam, xs].sum())


def mask_outside(patch: np.ndarray, seam_top: np.ndarray | None, seam_bottom: np.ndarray | None,
                 y0: int, x0: int, fill: int = 255) -> np.ndarray:
    """把字格裁片里缝另一侧的像素抹成背景。

    patch 是列图 [y0:y1, x0:x1] 的裁片；seam_* 是列图坐标下每个 x 的缝 y（索引从列图
    内容窗口的 x_lo 起）。上缝：行 < seam_top[x] 的像素属上一格 → 抹白；
    下缝：行 ≥ seam_bottom[x] 的像素属下一格 → 抹白。
    """
    out = patch.copy()
    h, w = out.shape[:2]
    if seam_top is not None:
        st = np.asarray(seam_top)[x0:x0 + w] - y0
        for x in range(min(w, len(st))):
            k = int(st[x])
            if k > 0:
                out[:min(k, h), x] = fill
    if seam_bottom is not None:
        sb = np.asarray(seam_bottom)[x0:x0 + w] - y0
        for x in range(min(w, len(sb))):
            k = int(sb[x])
            if k < h:
                out[max(0, k):, x] = fill
    return out
