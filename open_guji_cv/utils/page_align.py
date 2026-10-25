# -*- coding: utf-8 -*-
"""刻本页 ↔ 逐列整理本半叶的自动配页（Step3 `page_map` 策略用，见 `steps/row_segment_pagemap.py`）。

**指纹**：每页 9 列 × (2 + 21) 格（出格两格 + 正文 21 格）每格的墨占比（`slot_ink`），二值化后与
半叶的「哪格有字」（`occupancy`）逐格比，一致的比例就是得分。满列页彼此分不开，但它们的格位也一样，
配错一页不影响格位表；短列、抬头、卷末空列把整段钉住。

**对齐**（`align`）：先在全书半叶里粗找几个起点候选（各页对各半叶的得分矩阵上，页 i 在半叶 i + d ± 2
里取最高分、按偏移 d 求和，取最大的几个），每个候选附近各做一遍单调 DP，取总代价最小的。
DP：配一对的代价 ＝ 10 ×（1 − 得分）；跳页（封面、护叶、插图、重复扫描）、跳半叶（缺扫）各 `SKIP`；
空半叶白跳；前后半叶顺序对调多付 `SWAP`；两页指纹几乎一样（重复扫描）后一页白跳。
DP 完做局部重排（`_reorder`）：各页在 DP 给的位置 ± `REORDER_BAND` 个半叶里一对一重新分配，
专治扫描次序成片乱的册（vol11 几叶之内前后颠倒、夹着缺扫）；次序正常的册得分打平，原位不动。
最后回填：两个已配页之间只剩一个未用的有字半叶、中间又恰好一页没配上的，配给它（整页抬头、
大印页）。人工钉页（`pins`）当硬约束。

参数是 2026-10-25 殿本 vol21–50 实配定的（30 册 5000 多页，正文半叶无漏配）：跳页代价 1.5 时
vol44/46/50 奇数页指纹差被误判成缺扫，改 4；奇偶先验会在偏移变一格处造假对调，不用。
粗找放宽成带状、多候选与局部重排是 vol11 上补的（严格对角线把 vol11 配到了卷四十五）；
殿本 vol11/13/14/16/17/19/20/21 八册自动表与中心库人核过的表逐格一致（配准的页）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

N_SLOTS = 21
N_EXTRA = 2                 # 出格两格（抬头 -2、-1）
INK_THR = 0.05              # 格内墨占比过这条算有字（纸色深的页按页底色抬高，见 `binarize`）
EXTRA_THR = 0.07            # 出格格挨着上版框，框线墨会混进来，门槛再高一档
CELL_MARGIN_Y = 0.12        # 量墨时每格上下各让出的格高比例
CELL_MARGIN_X = 0.15        # 每列左右各让出的列宽比例（避开界行）
SKIP = 4.0                  # 跳页、跳半叶的代价（配一对的代价是 10 ×（1 − 得分））
SKIP_EMPTY = 0.2            # 跳过空半叶
SKIP_DUP = 0.1              # 跳过重复扫描的页
SWAP = 1.0                  # 前后半叶对调的额外代价
DUP_DIFF = 0.01             # 两页原始墨量指纹平均差小于这个算重复扫描
MARGIN = 40                 # 粗找的起点前后各放几个半叶做精对齐
LOW_SCORE = 0.6             # 得分低于这个的配对标「不确定」
COARSE_K = 4                # 粗找取几个起点候选，各做一遍精对齐，取总代价最小的
COARSE_BAND = 2             # 粗找时页 i 在半叶 i + d ± 这么多里取最高分
REORDER_BAND = 6            # 局部重排：每页只能挪到单调配上的半叶 ± 这么多以内
REORDER_STEP = 0.02         # 局部重排每挪一个半叶的代价（得分打平时留在原位）


def slot_ink(gray: np.ndarray, columns: list[tuple[float, float, float, float]],
             ink_threshold: int = 128) -> np.ndarray:
    """一页的墨量指纹：`columns` 从右到左每列 (x_left, x_right, frame_top, frame_bottom)，
    图像坐标（左上原点）。返回 (列数, N_EXTRA + N_SLOTS) 的墨占比。"""
    h, w = gray.shape[:2]
    b = gray < ink_threshold
    out = np.zeros((len(columns), N_EXTRA + N_SLOTS), dtype=np.float32)
    for c, (x0, x1, top, bot) in enumerate(columns):
        pitch = (bot - top) / N_SLOTS
        m = max(3, int((x1 - x0) * CELL_MARGIN_X))
        xa, xb = max(0, int(x0) + m), min(w, int(x1) - m)
        if xb <= xa or pitch <= 0:
            continue
        for k in range(N_EXTRA + N_SLOTS):
            s = k - N_EXTRA
            ya = int(top + s * pitch + pitch * CELL_MARGIN_Y)
            yb = int(top + (s + 1) * pitch - pitch * CELL_MARGIN_Y)
            if ya < 0 or yb > h or yb <= ya:
                continue
            out[c, k] = float(b[ya:yb, xa:xb].mean())
    return out


def binarize(grid: np.ndarray) -> np.ndarray:
    """墨占比 → 有字。门槛按本页底色自适应：纸色深、满页都有 0.05 的底墨时跟着抬高。"""
    base = min(float(np.percentile(grid[:, N_EXTRA:], 5)), 0.07)
    t = max(INK_THR, base + 0.045)
    out = grid > t
    out[:, :N_EXTRA] = grid[:, :N_EXTRA] > t + EXTRA_THR
    return out


def occupancy(layouts: list[tuple[int, dict]], ncol: int = 9) -> np.ndarray:
    """一个半叶的「哪格有字」：`layouts` 是 [(列号从 0, column_layout 行)]。"""
    o = np.zeros((ncol, N_EXTRA + N_SLOTS), dtype=bool)
    for c, lay in layouts:
        if not 0 <= c < ncol:
            continue
        for s in lay["slots"]:
            if 1 <= s <= N_SLOTS:
                o[c, s - 1 + N_EXTRA] = True
            elif -N_EXTRA <= s < 0:
                o[c, s + N_EXTRA] = True
    return o


@dataclass
class PageMatch:
    page: int
    half: int | None            # 半叶全局号；None ＝ 没配上（封面、护叶、插图……）
    score: float = 0.0
    how: str = "pair"           # pair / swap / reorder / gap / pin / dup / none
    confident: bool = True


@dataclass
class AlignResult:
    matches: dict[int, PageMatch] = field(default_factory=dict)
    start: int = 0              # 精对齐窗口的首个半叶
    end: int = 0                # 用到的最后一个半叶 + 1
    dups: list[int] = field(default_factory=list)


def _scores(G: list[np.ndarray | None], O: np.ndarray, empty: np.ndarray,
            inks: list[float]) -> np.ndarray:
    """(页数, 半叶数) 得分矩阵：逐格一致比例。没框的页只认空半叶。"""
    n, m = len(G), O.shape[0]
    cells = O.shape[1] * O.shape[2]
    Of = O.reshape(m, cells).astype(np.float32)
    S = np.zeros((n, m), dtype=np.float32)
    for i, g in enumerate(G):
        if g is None or g.shape != O.shape[1:]:
            S[i] = np.where(empty & (inks[i] < 0.03), 1.0, 0.0)
            continue
        gf = g.reshape(cells).astype(np.float32)
        agree = Of @ gf + (1 - Of) @ (1 - gf)
        S[i] = agree / cells
    return S


def coarse_starts(S: np.ndarray, k: int = COARSE_K) -> list[int]:
    """全书粗找起点候选：页 i ↔ 半叶 i + d 附近（± `COARSE_BAND`）得分和最高的 `k` 个偏移 d，
    彼此至少隔 `MARGIN`。放宽成带状是为了扫描次序乱（vol11 前后半叶成片对调）的册：严格对角线上
    对调的页都配错，真起点的和反而输给满页多的别处。"""
    n, m = S.shape
    if m <= n:
        return [0]
    from scipy.ndimage import maximum_filter1d
    M = maximum_filter1d(S, size=2 * COARSE_BAND + 1, axis=1, mode="constant", cval=0.0)
    nd = m - n + 1
    best = np.zeros(nd, dtype=np.float64)
    for i in range(n):
        best += M[i, i:i + nd]
    out: list[int] = []
    for d in np.argsort(-best, kind="stable"):
        if all(abs(int(d) - e) > MARGIN for e in out):
            out.append(int(d))
            if len(out) >= k:
                break
    return out


def align(pages: list[int], grids: list[np.ndarray | None], inks: list[float],
          O: np.ndarray, empty: np.ndarray, cover: np.ndarray,
          pins: dict[int, int | None] | None = None,
          raw: list[np.ndarray | None] | None = None) -> AlignResult:
    """`pages` 本册页号（升序），`grids` 各页二值指纹（没框为 None），`inks` 各页整页墨量；
    `O` 全书半叶占格 (m, 列, 格)，`empty` 空半叶，`cover` 牌记半叶；`pins` 人工钉页 {页: 半叶或 None}；
    `raw` 各页原始墨量指纹（认重复扫描用）。"""
    pins = pins or {}
    n = len(pages)
    S_all = _scores(grids, O, empty, inks)
    pinned = [h for h in pins.values() if h is not None]
    dup = [False] * n
    if raw is not None:
        for i in range(1, n):
            a, b = raw[i], raw[i - 1]
            dup[i] = (a is not None and b is not None and a.shape == b.shape
                      and float(np.abs(a - b).mean()) < DUP_DIFF and pages[i] not in pins)
    starts = coarse_starts(S_all)
    best = None
    for d0 in starts:
        lo = max(0, min([d0] + pinned) - MARGIN)
        hi = min(O.shape[0], max([d0 + n] + [h + 1 for h in pinned]) + MARGIN)
        total, res = _align_window(pages, S_all, lo, hi, empty, cover, pins, dup)
        if best is None or total < best[0]:
            best = (total, res)
    return best[1]


def _align_window(pages, S_all, lo, hi, empty, cover, pins, dup) -> tuple[float, AlignResult]:
    """在半叶 [lo, hi) 里做单调 DP（见模块头），返回（总代价，结果）。"""
    n = len(pages)
    S = S_all[:, lo:hi]
    m = hi - lo
    INF = 1e18
    cost = 10 * (1 - S.astype(np.float64))
    for i, p in enumerate(pages):
        if p in pins:
            h = pins[p]
            cost[i, :] = INF
            if h is not None and lo <= h < hi:
                cost[i, h - lo] = 0.0
    D = np.full((n + 1, m + 1), INF)
    D[0, :] = 0.0                                   # 起点在窗口里自由
    B: dict[tuple[int, int], tuple[int, int, str]] = {}
    skip_half = np.where(empty[lo:hi] | cover[lo:hi], SKIP_EMPTY, SKIP)
    for i in range(n + 1):
        for j in range(m + 1):
            d = D[i, j]
            if d >= INF:
                continue
            if i < n and j < m and d + cost[i, j] < D[i + 1, j + 1]:
                D[i + 1, j + 1] = d + cost[i, j]
                B[i + 1, j + 1] = (i, j, "pair")
            if i + 1 < n and j + 1 < m:
                c = d + cost[i, j + 1] + cost[i + 1, j] + SWAP
                if c < D[i + 2, j + 2]:
                    D[i + 2, j + 2] = c
                    B[i + 2, j + 2] = (i, j, "swap")
            if i < n:
                sk = INF if pages[i] in pins and pins[pages[i]] is not None else (SKIP_DUP if dup[i] else SKIP)
                if d + sk < D[i + 1, j]:
                    D[i + 1, j] = d + sk
                    B[i + 1, j] = (i, j, "skip_page")
            if j < m and d + skip_half[j] < D[i, j + 1]:
                D[i, j + 1] = d + skip_half[j]
                B[i, j + 1] = (i, j, "skip_half")
    j_end = int(np.argmin(D[n]))
    total = float(D[n, j_end])
    res = AlignResult(start=lo, end=lo + j_end)
    i, j = n, j_end
    while (i, j) in B:
        pi, pj, op = B[i, j]
        if op == "pair":
            res.matches[pages[pi]] = PageMatch(pages[pi], lo + pj, float(S[pi, pj]),
                                               "pin" if pages[pi] in pins else "pair")
        elif op == "swap":
            res.matches[pages[pi]] = PageMatch(pages[pi], lo + pj + 1, float(S[pi, pj + 1]), "swap")
            res.matches[pages[pi + 1]] = PageMatch(pages[pi + 1], lo + pj, float(S[pi + 1, pj]), "swap")
        i, j = pi, pj
    _reorder(res, pages, S_all, empty, cover, pins, dup)
    # 回填：两个已配页之间只剩一个未用的有字半叶、中间恰好一页没配上
    used = {mt.half for mt in res.matches.values()}
    for k in range(1, n - 1):
        p = pages[k]
        a, b = res.matches.get(pages[k - 1]), res.matches.get(pages[k + 1])
        if p in res.matches or p in pins or a is None or b is None:
            continue
        free = [h for h in range(a.half + 1, b.half) if h not in used and not empty[h] and not cover[h]]
        if len(free) == 1:
            res.matches[p] = PageMatch(p, free[0], float(S_all[k, free[0]]), "gap")
            used.add(free[0])
    for k, p in enumerate(pages):
        mt = res.matches.get(p)
        if mt is None:
            res.matches[p] = PageMatch(p, None, 0.0, "dup" if dup[k] else ("pin" if p in pins else "none"))
        elif mt.how not in ("pin",) and mt.score < LOW_SCORE:
            mt.confident = False
    res.dups = [pages[k] for k in range(n) if dup[k]]
    return total, res


def _reorder(res: AlignResult, pages: list[int], S_all: np.ndarray, empty: np.ndarray,
             cover: np.ndarray, pins: dict[int, int | None], dup: list[bool]) -> None:
    """局部重排：单调 DP 配上的页、和夹在其间没配上的页，在各自半叶（没配上的按前一页推）
    ± `REORDER_BAND` 里重新一对一分配（匈牙利法），代价 ＝ 配对代价 ＋ 每挪一个半叶 `REORDER_STEP`；
    没配上的页也可以照旧不配（代价 `SKIP`）。扫描次序成片乱的册（vol11：几叶之内前后颠倒，
    不只是相邻两页对调）靠这一步配回；次序正常的册得分打平就留在原位，结果不变。
    空半叶、牌记半叶上的页和别的方式配上的页（钉页、重复扫描）不动，它们占的半叶也不让出来。"""
    from scipy.optimize import linear_sum_assignment
    still = empty | cover
    rows: list[tuple[int, int, bool]] = []          # (页序, 中心半叶, 原来配上没有)
    last = None
    for k, p in enumerate(pages):
        mt = res.matches.get(p)
        if mt is not None:
            last = (k, mt.half)
            if p not in pins and mt.how in ("pair", "swap") and not still[mt.half]:
                rows.append((k, mt.half, True))
        elif last is not None and p not in pins and not dup[k]:
            rows.append((k, last[1] + k - last[0], False))
    if len(rows) < 2:
        return
    moving = {res.matches[pages[k]].half for k, _, on in rows if on}
    taken = {mt.half for mt in res.matches.values() if mt.half is not None} - moving
    lo_h, hi_h = 0, S_all.shape[1]
    cols = sorted({h for _, c, _ in rows for h in range(c - REORDER_BAND, c + REORDER_BAND + 1)
                   if lo_h <= h < hi_h and not still[h] and h not in taken})
    ci = {h: j for j, h in enumerate(cols)}
    big = 1e6
    C = np.full((len(rows), len(cols) + len(rows)), big)
    for r, (k, c, on) in enumerate(rows):
        for h in range(c - REORDER_BAND, c + REORDER_BAND + 1):
            if h in ci:
                C[r, ci[h]] = 10 * (1 - float(S_all[k, h])) + REORDER_STEP * abs(h - c)
        if not on:
            C[r, len(cols) + r] = SKIP
    rr, cc = linear_sum_assignment(C)
    for r, j in zip(rr, cc):
        k, c, on = rows[r]
        if j >= len(cols) or C[r, j] >= big:
            continue
        h = cols[j]
        if not on or h != res.matches[pages[k]].half:
            res.matches[pages[k]] = PageMatch(pages[k], h, float(S_all[k, h]), "reorder")
