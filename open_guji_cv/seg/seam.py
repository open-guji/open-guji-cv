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

from collections.abc import Sequence

import numpy as np

SEAM_BAND = 20      # 走廊半宽（px）。2026-09-05 折线金标 19 条：人的折线离直线最远 21px，
                    # 12 时 16/19 缝无墨，20 时 18/19；墨的代价挡住了绕进邻字身，20 仍安全
SEAM_STEP = 2       # 每前进一列纵向最多移动的像素
SEAM_TURN = 0.02    # 每 1px 纵向移动的代价（一个墨像素 = 1）
SEAM_MAX_INK = 3    # 缝上墨像素超过这个数就不用缝（保持直线切点）。60 页验收：缝上墨 0 / 1–3 px 的
                    # 相邻字位人审率 1.99% / 1.92%，4–10 px 的 4.40%——绕不开的缝多半在切自己的笔画
SEAM_BAND_WIDE = 40 # 分级走廊：±SEAM_BAND 里找不到 ≤SEAM_MAX_INK 的缝时，再到 ±40 里找一次。
                    # 231 条折线金标（2026-09-06）：只放宽"本来要放弃"的那些，≤6px 93.9 → 96.1%，
                    # >12px 6 → 1（vol01:76:9:20 會/公 那条无墨路离直线 25px）；若对已有 1–3px 墨的缝也
                    # 放宽，会有 7 条换到别的空隙里去、偏 22–41px——所以触发条件是 > SEAM_MAX_INK，不是 > 0


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
    cost, back = seam_dp(col, tie, step, turn)
    j = int(np.argmin(cost))
    seam = np.empty(w, dtype=int)
    for x in range(w - 1, -1, -1):
        seam[x] = j + lo
        j -= int(back[x, j])
    return seam


def seam_dp(col: np.ndarray, tie: np.ndarray, step: int, turn: float):
    """走廊 DP 的前向一遍：col 为 (n, w) 每行每列的代价，返回 (末列累计代价, 回溯表 back[x, j])。

    提速（2026-11-03，全唐文册06 一页 1,100 余次）：原先每列 `np.full` 新开 (2·step+1, n) 数组、
    再逐偏移赋值；现在预分配两边垫 inf 的 pad 与 cand，逐偏移只做一次切片加法。加法顺序、
    argmin 的平局次序（偏移 -step..+step）都与原写法相同，结果逐位相同。"""
    n, w = col.shape
    offsets = np.arange(-step, step + 1)
    pens = [turn * d if d >= 0 else turn * (-d) for d in offsets]
    cost = col[:, 0] + tie
    back = np.zeros((w, n), dtype=np.int16)
    pad = np.full(n + 2 * step, np.inf)
    cand = np.empty((len(offsets), n))
    ar = np.arange(n)
    for x in range(1, w):
        pad[step:step + n] = cost
        for i, d in enumerate(offsets):
            # cand[i, j] = cost[j - d] + turn·|d|，越界处 pad 为 inf
            np.add(pad[step - d:step - d + n], pens[i], out=cand[i])
        best_i = np.argmin(cand, axis=0)
        cost = cand[best_i, ar] + col[:, x] + tie
        back[x] = offsets[best_i]
    return cost, back


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


# ── 一行字自己的格线（2026-11-03）────────────────────────────────────
# 给定一段的上下端和格数，在这一行的墨投影上挑 n−1 条横切线。用途：史記文淵閣本写本雙行小注左右两行
# 各写各的、字距不同、会错开半格，两行共用一套格线时总有一行被拦腰切（02:12:6「州上洛縣」、08:11:8「邑侯」），
# 两行各在自己的墨投影上挑切线就分开了（impl/keben/row_boundaries `jiazhu_rows`）。殿本刻本两行逐字对齐，用不上。
# 挑法是一次 DP：切线落在墨少的行，格高贴近段均高；`anchor` 给了时再轻轻拉向原来的格线（没墨的地方不乱挪）。
def fit_row_cuts(ink_rows: np.ndarray, top: int, bottom: int, n: int, *,
                 anchor: Sequence[float] | None = None,
                 pitch_w: float = 0.3, anchor_w: float = 0.02,
                 min_h: float = 0.4, max_h: float = 1.8, band: int = 0) -> list[float] | None:
    """在 `[top, bottom)` 里挑 n−1 条切线，返回含两端的 n+1 个 y（升序）。

    - `ink_rows`：这一行每个 y 的墨占比（0..1，按行宽归一）；
    - 代价 = Σ 切线处墨占比（`band`>0 时取切线 ±band 行里最小）
      + `pitch_w`·Σ(格高/均高 − 1)² + `anchor_w`·Σ|切线 − anchor|/均高；
    - 格高限在 [`min_h`, `max_h`]×均高；`anchor` 是 n+1 个原格线（只用中间 n−1 条）。
    排不下（段太矮、n<1）返回 None。"""
    top, bottom = int(round(top)), int(round(bottom))
    L = bottom - top
    if n < 1 or L < n * 2:
        return None
    if n == 1:
        return [float(top), float(bottom)]
    P = L / n
    lo, hi = max(1, int(np.floor(min_h * P))), int(np.ceil(max_h * P))
    seg = np.asarray(ink_rows[top:bottom], dtype=np.float64)
    k = 2 * band + 1
    pad = np.pad(seg, band, mode="edge")
    cost = np.lib.stride_tricks.sliding_window_view(pad, k).min(axis=1) if band > 0 else seg.copy()
    INF = np.inf
    # dp[y]：已放到第 j 条切线、它落在 y（相对 top）时的最小代价；y=0 是段顶
    dp = np.full(L + 1, INF)
    dp[0] = 0.0
    back: list[np.ndarray] = []
    for j in range(1, n + 1):
        nd = np.full(L + 1, INF)
        arg = np.zeros(L + 1, dtype=np.int64)
        for h in range(lo, hi + 1):
            prev = dp[:L + 1 - h]
            c = prev + pitch_w * (h / P - 1.0) ** 2
            better = c < nd[h:]
            nd[h:][better] = c[better]
            arg[h:][better] = h
        if j < n:
            ys = np.arange(L + 1)
            nd[:L] += cost[:L]
            nd[L] = INF                       # 中间的切线不能落在段底
            if anchor is not None:
                nd += anchor_w * np.abs(ys + top - float(anchor[j])) / P
        back.append(arg)
        dp = nd
    if not np.isfinite(dp[L]):
        return None
    ys_out = [L]
    y = L
    for j in range(n, 0, -1):
        h = int(back[j - 1][y])
        y -= h
        ys_out.append(y)
    if y != 0:
        return None
    return [float(top + v) for v in reversed(ys_out)]


# ── 墨块切割量（2026-11-13，A22，史記 r54 少见字页劈字）────────────────────────────
# 一条水平直线放在某一行，会把多少连通墨块劈成上下两半。
#
# 行投影（每行多少墨）只说「这一行白不白」，说不出「这一行是不是字缝」：写本字距不匀、字常伸出名义格，
# 两字之间往往没有干净的白行，行墨最少的那一行可能正穿着上字的长捺。切割量换个量法——把列图的墨按连通块分开，
# 一条线落在 y，每个跨过 y 的连通块被劈成上下两截，取**较小那截的墨量**求和：
#
# - 线落在两个不粘连的字之间：没有连通块跨线，切割量 0（哪怕这一行上有墨，那墨也整块在线的一侧）；
# - 线擦过某字的笔尖：被劈下的那截很小，切割量小；
# - 线劈在字中间：两截都大，切割量大。
#
# 史記 SJ 用同一量法查全书：强档（切割量 ≥800、挪后 ≤1/10）1,170 条，抽 12 条看图全是真劈字。
#
# 本原语只量，不挑线；怎么用切割量挑格线见 `impl/keben/row_boundaries.snap_by_cut`。


def cut_cost_profile(ink: np.ndarray, max_h: float | None = None, min_area: int = 1) -> np.ndarray:
    """ink：H×W 布尔（True＝墨）。返回长 H+1 的数组 `c`：`c[y]` 是水平线放在第 y 行**上沿**（第 0..y-1 行在线上、
    第 y..H-1 行在线下）时的切割量＝Σ 跨线连通块 min(线上墨, 线下墨)（像素数）。`c[0]`、`c[H]` 恒为 0。

    - `max_h`：纵向跨度超过它（像素）的连通块不算——贯穿整列的界行残段、版框竖线、大片墨渍不是字，
      算进来会让整列切割量都高、高处还在列中间。None＝都算。
    - `min_area`：面积小于它的连通块不算（墨点噪声）。

    8 连通（同 Step4 归属图）。"""
    ink = np.asarray(ink, dtype=bool)
    h = ink.shape[0]
    out = np.zeros(h + 1, dtype=np.float64)
    if ink.size == 0 or not ink.any():
        return out
    import cv2
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    for k in range(1, n):
        top, hh, area = int(stats[k, cv2.CC_STAT_TOP]), int(stats[k, cv2.CC_STAT_HEIGHT]), int(stats[k, cv2.CC_STAT_AREA])
        if hh < 2 or area < min_area or (max_h is not None and hh > max_h):
            continue
        rows = (lab[top:top + hh] == k).sum(axis=1).astype(np.float64)
        above = np.cumsum(rows)[:-1]                   # 线在 top+1..top+hh-1 时线上的墨
        out[top + 1:top + hh] += np.minimum(above, area - above)
    return out


def cut_cost_sides(ink: np.ndarray, max_h: float | None = None, min_area: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """`cut_cost_profile` 按被劈下的小截在哪一边拆成两份：`(up, down)`，各长 H+1。`up[y]`＝线在 y 时小截在线**上**的那些
    连通块的小截墨量和，`down[y]`＝小截在线**下**的。两截一样大各记一半，`up + down == cut_cost_profile(...)`。

    用处：线劈着字时该往哪边挪——小截在下（`down` 大）说明线切在上字的字脚，往下挪才把字脚还给上字；往上挪
    会把上字的大半截推给下一格（上下结构的字：「實」切在貝腿上，往上挪会落进宀与貫之间的白缝）。"""
    ink = np.asarray(ink, dtype=bool)
    h = ink.shape[0]
    up = np.zeros(h + 1, dtype=np.float64)
    down = np.zeros(h + 1, dtype=np.float64)
    if ink.size == 0 or not ink.any():
        return up, down
    import cv2
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    for k in range(1, n):
        top, hh, area = int(stats[k, cv2.CC_STAT_TOP]), int(stats[k, cv2.CC_STAT_HEIGHT]), int(stats[k, cv2.CC_STAT_AREA])
        if hh < 2 or area < min_area or (max_h is not None and hh > max_h):
            continue
        rows = (lab[top:top + hh] == k).sum(axis=1).astype(np.float64)
        above = np.cumsum(rows)[:-1]
        below = area - above
        up[top + 1:top + hh] += np.where(above < below, above, np.where(above == below, above / 2, 0.0))
        down[top + 1:top + hh] += np.where(below < above, below, np.where(above == below, below / 2, 0.0))
    return up, down
