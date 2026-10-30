"""列距救援（Step1 后处理，2026-10-23 sheldon 定缺省开）：自由模式探出的列网里有列宽出了「列宽带」（殿本列宽极一致），
按「列距均匀」重定这一页的竖线。

**病**（殿本 vol11–20 v0.5.9 九页：vol13 p75、vol14 p103/186、vol16 p8/120、vol19 p29/86、vol20 p68/113）：
自由模式在某一列里多挑了一条假竖线（字心、夹注缝），把一列劈成两窄列；凑够 `expected_cols+1` 条线，
外侧真列的那条外框线就挤掉了——**一整列落在网外，字悄悄丢了**，后面列号全错一位。

**做法**（都只在页上有列宽出带时才走；正常页逐字节不变）：
0. 外列窄、外侧 0.5 列宽内有界行残段（版框）：外框线吸到那条残段上（`snap_outer_to_frame`）。殿本 vol40 p14、
   vol46 p118/p148：版心条印在版框外，自由模式的外框线落在框里的字边上，外列只剩 0.75–0.83 列宽；
1. 网格模式重探（`column_grid`，版框定死、列距均匀）；
2. 网格选不出版框对时（外框只有粗外条、不在候选池里）：去掉劈开窄对的那条线，在墨多的一侧
   按中位列距补一条外框线（记成插值线）。
3. 前两条都不成（假竖线不止一条、网格只对了一半，vol20 p113：c3 里挑了三条错线、真界行淡，网格对上了
   c3、c4 却在外侧挑歪）：自由模式的线、网格模式的线、两侧按列距外推的外框线（有字那侧）放进一个池，
   挑一串列宽全在带内的线，自由线优先、网格线其次、外推线最后（`fuse`）。池里还有界行残段（`_rule_ridges`：
   竖墨线连续 ≥ 0.8 列宽）：vol16 p8 全页小字雙行，版心里没有界行、只在天头有一截，自由模式把一条线探进字缝、
   又在末列多挑一条；外推的外框线 0.15 列宽内有残段就吸过去。

4. 前几条都不成（界行淡到自由模式探不出、网格线又差十几二十 px，v0.5.17 首跑 vol24 p69、vol29 p28、vol37 p76、
   vol48 p121）：在网格网（再不成用自由网）上，把出带列两边的线逐轮吸到附近的淡界行细峰上，没有界行就吸到字间
   空白中点，列宽都进带才收（`snap_lines`）。网格模式线数比自由模式多（自由模式漏了一条线，vol45 p54）也照收。

**接受条件**：新列网每条正文列都在列宽带内，且至少一半的线与原线重合（±`tol` px）
——防止网格模式在卷端大印页、书名页上挑出另一套网（vol20 p179）。不满足就原样返回。
另外，外侧贴着版框（有界行残段）的旧外列不许被甩出新网（`drops_framed_col`）：1–3 条路在版心条那样的
框外墨上外推出一列、把整网平移一列，框里的真列整列丢掉（v0.5.17 首跑 vol40 p14、vol46 p118/p148）。

纯几何，不改 `border_geometry`（那是三个步骤的 `code_deps`）。
"""
from __future__ import annotations

import statistics
from copy import deepcopy
from dataclasses import replace

import cv2
import numpy as np

from .column_pair_merge import line_xs
from .column_types import classify_columns

#: 列宽带（列宽 / 页中位列宽）。殿本 vol04–20 共 2,969 页正文（2026-10-23 量）：内列 99.9% 在
#: 0.907–1.088、99% 在 0.958–1.046；最外两列量到外框，偏宽，99.9% 在 0.84–1.26。超出带就触发救援，
#: 救出来的新列网也得全落在带内才接受。
INNER = (0.9, 1.1)
OUTER = (0.85, 1.3)
NARROW = 0.7     # drop_and_extend 认「窄对」：两条相邻列各 < 此比例 × 中位、和落在内列带里
TOL = 8.0
#: 补外框那一侧要有字：墨像素占比下限（按二值图量，殿本正文列约 0.08–0.15，空白列 < 0.01）
MIN_INK = 0.02
#: 界行残段：一条竖向墨线连续 ≥ 此比例 × 中位列宽（容 3px 断口）。字的竖笔不过一格高（殿本 ≤ 0.67 列宽），
#: 全页小字雙行、版心里没有界行的页（vol16 p8）界行只在天头那一截，也有 1.2 列宽以上
RULE_RUN = 0.8
#: 吸线（`snap_lines`）：界行淡到自由模式探不出、网格线又差十几二十 px 的页，出带列两边的线就近吸到
#: 淡界行（投影细峰，峰值 ≥ RULE_PEAK、两侧 RULE_HALF px 外落到一半以下，±SNAP_RULE 列宽内）上；
#: 没有界行就吸到字间空白（投影 < BLANK 的连续段）的中点（±SNAP_BLANK 列宽内）。
RULE_PEAK = 0.02
RULE_HALF = 8
SNAP_RULE = 0.3
SNAP_BLANK = 0.15
BLANK = 0.01
#: 外框吸附：外侧这么宽（× 中位列宽）以内找版框的界行残段
FRAME_REACH = 0.5
#: 借形状的自由线斜率与本页中位斜率之差上限（殿本界行斜率差一般 < 0.005）
SLOPE_TOL = 0.01


def _body_widths(xs, leaf_layout):
    return [c.width for c in classify_columns(xs, leaf_layout=leaf_layout) if c.kind == "body"]


def out_of_band(xs, *, leaf_layout: str = "single") -> set[int] | None:
    """列宽出带的列号（1 起，与 `classify_columns` 同口径）。正文列不到 5 条（书名页、卷端大印页）返回 None＝不判。"""
    cols = classify_columns(xs, leaf_layout=leaf_layout)
    body = [c for c in cols if c.kind == "body"]
    if len(body) < 5:
        return None
    m = statistics.median(c.width for c in body)
    # 非正文列（贴页边的 edge 列）宽度本来不受带约束，但它两边的线也可以动（vol19 p86：末两列并成一条 edge 列）
    bad = {c.col for c in cols if c.kind != "body"} if any(not 0.9 <= c.width / m <= 1.1 for c in body) else set()
    for i, c in enumerate(body):
        lo, hi = OUTER if i in (0, len(body) - 1) else INNER
        if not lo <= c.width / m <= hi:
            bad.add(c.col)
    return bad if any(c.col in bad for c in body) else set()


def in_band(xs, *, leaf_layout: str = "single") -> bool | None:
    """每条正文列都在列宽带里？不判的页返回 None。"""
    bad = out_of_band(xs, leaf_layout=leaf_layout)
    return None if bad is None else not bad


def keeps_good_lines(old, new, bad_cols, tol: float = TOL, ridges=None) -> bool:
    """列宽合格的列，两边的界行不许动：旧线里不挨着出带列的，新网里都得有（±tol）。
    防止网格模式把印得好好的界行挪到空白里（vol13 p46：外列偏宽 1.3，网格把内部三条真界行各挪 9px）。
    给了 `ridges`（`_rule_ridges` 量出的界行残段）就只护 ±tol 内有残段的旧线：没有残段的线是自由模式探进字里的，
    列宽碰巧合格也不算真界行（换图源 vol40 新 p1：卷首大印页印泥斑点里自由模式连挑三条字心线，
    中间两列宽度合格，网格探对了却被这条拦下）。"""
    movable = {i for c in bad_cols for i in (c - 1, c)}
    if ridges is not None:
        movable |= {i for i, x in enumerate(old) if not any(abs(x - r) <= tol for r in ridges)}
    return all(any(abs(x - y) <= tol for y in new) for i, x in enumerate(old) if i not in movable)


def needs_rescue(xs, *, leaf_layout: str = "single") -> bool:
    return in_band(xs, leaf_layout=leaf_layout) is False


def is_clean(xs, *, leaf_layout: str = "single") -> bool:
    return in_band(xs, leaf_layout=leaf_layout) is True


def n_shared(a, b, tol: float = TOL) -> int:
    return sum(1 for x in a if any(abs(x - y) <= tol for y in b))


def drop_and_extend(res, gray: np.ndarray, *, leaf_layout: str = "single",
                    ink_threshold: int = 128) -> bool:
    """去掉劈开窄对的那条线、在墨多的一侧补外框线。改了 `res` 返回 True；不合条件原样返回 False。"""
    xs = line_xs(res)
    gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
    med = statistics.median(gaps)
    pairs = [i for i in range(len(gaps) - 1)
             if gaps[i] < NARROW * med and gaps[i + 1] < NARROW * med
             and INNER[0] * med <= gaps[i] + gaps[i + 1] <= INNER[1] * med]
    if len(pairs) != 1:
        return False
    drop = pairs[0] + 1
    v = list(res.verticals)
    filled = list(res.vline_filled) or [False] * len(v)
    vs = list(res.verticals_straight) if len(res.verticals_straight) == len(v) else None
    del v[drop], filled[drop]
    if vs is not None:
        del vs[drop]
    keep = [x for i, x in enumerate(xs) if i != drop]
    # 两侧候选外框：按中位列距外推；量候选列里的墨（规范空间右上原点 → 原图 x = W−1−x）
    H, W = gray.shape[:2]
    top = int(res.top.y_at(0.0)) if res.top is not None else 0
    bot = int(res.bottom.y_at(0.0)) if res.bottom is not None else H - 1

    def ink(x0, x1):
        a, b = int(round(W - 1 - max(x0, x1))), int(round(W - 1 - min(x0, x1)))
        if a < 0 or b > W - 1 or b - a < 10:
            return -1.0
        pad = (b - a) // 6     # 不量贴着界行的那几 px
        return float((gray[top:bot, a + pad:b - pad] < ink_threshold).mean())

    lo_ink = ink(keep[0] - med, keep[0])
    hi_ink = ink(keep[-1], keep[-1] + med)
    if max(lo_ink, hi_ink) < MIN_INK:
        return False
    if lo_ink >= hi_ink:
        v.insert(0, replace(v[0], x_at_top=v[0].x_at_top - med))
        filled.insert(0, True)
        if vs is not None:
            vs.insert(0, replace(vs[0], x_at_top=vs[0].x_at_top - med))
    else:
        v.append(replace(v[-1], x_at_top=v[-1].x_at_top + med))
        filled.append(True)
        if vs is not None:
            vs.append(replace(vs[-1], x_at_top=vs[-1].x_at_top + med))
    new_xs = line_xs(replace(res, verticals=v))
    if not is_clean(new_xs, leaf_layout=leaf_layout):
        return False
    res.verticals = v
    res.vline_filled = filled
    if vs is not None:
        res.verticals_straight = vs
    return True


def _ink(res, gray, x0, x1, ink_threshold):
    """规范空间 [x0, x1) 这条列里的墨占比（原图 x = W−1−x，不量贴着界行的那几 px）；出图返回 -1。"""
    H, W = gray.shape[:2]
    top = int(res.top.y_at(0.0)) if res.top is not None else 0
    bot = int(res.bottom.y_at(0.0)) if res.bottom is not None else H - 1
    a, b = int(round(W - 1 - max(x0, x1))), int(round(W - 1 - min(x0, x1)))
    if a < 0 or b > W - 1 or b - a < 10:
        return -1.0
    pad = (b - a) // 6
    return float((gray[top:bot, a + pad:b - pad] < ink_threshold).mean())


def _rule_ridges(res, gray, x0, x1, min_run, ink_threshold):
    """规范空间 (x0, x1) 里像界行的竖墨线：按自由线的中位斜率拉直，逐列量最长连续墨段（容 3px 断口），
    ≥ min_run 的列按 10px 内取最长者归并。返回 x（版框中高处，与 `line_xs` 同口径）。"""
    H, W = gray.shape[:2]
    top = max(int(res.top.y_at(0.0)) if res.top is not None else 0, 0)
    bot = min(int(res.bottom.y_at(0.0)) if res.bottom is not None else H - 1, H - 1)
    if bot - top < 10:
        return []
    ys = np.arange(top, bot)
    slope = statistics.median(v.slope for v in res.verticals)
    xs = np.arange(int(np.ceil(x0)), int(x1))
    px = np.rint(W - 1 - (xs[None, :] + slope * (ys[:, None] - (top + bot) / 2.0))).astype(int)
    ok = (px >= 0) & (px < W)
    ink = np.where(ok, gray[ys[:, None], np.clip(px, 0, W - 1)] < ink_threshold, False).astype(np.uint8)
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((4, 1), np.uint8))
    run = np.zeros(len(xs), int)
    cur = np.zeros(len(xs), int)
    for row in ink:
        cur = (cur + 1) * row
        np.maximum(run, cur, out=run)
    out = []
    for i in np.flatnonzero(run >= min_run):
        if out and xs[i] - out[-1][0] <= 10:
            if run[i] > out[-1][1]:
                out[-1] = (int(xs[i]), int(run[i]))
        else:
            out.append((int(xs[i]), int(run[i])))
    return [float(x) for x, _ in out]


def fuse(res, g, gray: np.ndarray, bad_cols, *, leaf_layout: str = "single", ink_threshold: int = 128) -> bool:
    """自由线＋网格线＋界行残段＋有字一侧的外推外框线里挑一串列宽都在带内、线数不变的线（自由 2 分、网格与
    残段 1 分、外推 0 分，取总分最高；外推线 0.15 列宽内有残段就吸过去、记 1 分）。列宽合格的列两边的线不许动（`keeps_good_lines`）。改了 `res` 返回 True；挑不出、
    或挑出的网不干净就原样返回 False。"""
    xs, gx = line_xs(res), line_xs(g)
    n = len(xs)
    med = statistics.median(_body_widths(xs, leaf_layout))
    def straight(r):
        return list(r.verticals_straight) if len(r.verticals_straight) == len(r.verticals) else list(r.verticals)
    pool = [(x, 2, v, False, s) for x, v, s in zip(xs, res.verticals, straight(res))]
    # 网格线只拿来替换自由线范围以内的线；外侧整列只按列距外推、且那侧要有字（网格在外侧可能挑出另一套网）
    pool += [(x, 1, v, False, s) for x, v, s in zip(gx, g.verticals, straight(g))
             if xs[0] < x < xs[-1] and all(abs(x - y) > TOL for y in xs)]
    # 界行残段（自由模式漏探或探偏的真界行，vol16 p8）：借离它最近、斜率正常的自由线的形状平移过去
    # （探偏的线常是斜的：vol16 p8 那条从天头的界行斜到字缝里）
    ridges = _rule_ridges(res, gray, xs[0] - 1.2 * med, xs[-1] + 1.2 * med, RULE_RUN * med, ink_threshold)
    k_med = statistics.median(v.slope for v in res.verticals)
    shape = [i for i in range(n) if abs(res.verticals[i].slope - k_med) <= SLOPE_TOL] or list(range(n))
    taken = [t[0] for t in pool]
    for r in ridges:
        if xs[0] < r < xs[-1] and all(abs(r - y) > TOL for y in taken):
            j = min(shape, key=lambda i: abs(xs[i] - r))
            pool.append((r, 1, replace(res.verticals[j], x_at_top=res.verticals[j].x_at_top + r - xs[j]), False,
                         replace(straight(res)[j], x_at_top=straight(res)[j].x_at_top + r - xs[j])))
    for x, v, s, sign in ((xs[0], res.verticals[0], straight(res)[0], -1),
                          (xs[-1], res.verticals[-1], straight(res)[-1], 1)):
        if _ink(res, gray, x, x + sign * med, ink_threshold) >= MIN_INK:
            near = [r for r in ridges if abs(r - (x + sign * med)) <= 0.15 * med]
            d = min(near, key=lambda r: abs(r - (x + sign * med))) - x if near else sign * med
            pool.append((x + d, 1 if near else 0, replace(v, x_at_top=v.x_at_top + d), not near,
                         replace(s, x_at_top=s.x_at_top + d)))
    pool.sort(key=lambda t: t[0])

    def ok(gap, k):
        lo, hi = OUTER if k in (0, n - 2) else INNER
        return lo * med <= gap <= hi * med
    # best[i][k]：以 pool[i] 收尾、已挑 k+1 条线的最高分与前驱
    best = [[None] * n for _ in pool]
    for i, t in enumerate(pool):
        best[i][0] = (t[1], None)
        for k in range(1, n):
            cand = [(best[j][k - 1][0] + t[1], j) for j in range(i)
                    if best[j][k - 1] is not None and ok(t[0] - pool[j][0], k - 1)]
            best[i][k] = max(cand) if cand else None
    ends = [(best[i][n - 1][0], i) for i in range(len(pool)) if best[i][n - 1] is not None]
    if not ends:
        return False
    chain, i, k = [], max(ends)[1], n - 1
    while i is not None:
        chain.append(pool[i])
        i, k = best[i][k][1], k - 1
    chain.reverse()
    new_xs = [t[0] for t in chain]
    if (not is_clean(new_xs, leaf_layout=leaf_layout) or n_shared(new_xs, xs) * 2 < n
            or not keeps_good_lines(xs, new_xs, bad_cols)):
        return False
    res.verticals = [t[2] for t in chain]
    res.vline_filled = [t[3] for t in chain]
    res.verticals_straight = [t[4] for t in chain]
    return True


def _profile(res, gray, x0, x1, ink_threshold):
    """规范空间 [x0, x1) 逐列的墨占比（版框上下沿之间，按自由线中位斜率拉直）。返回 (xs, 占比)。"""
    H, W = gray.shape[:2]
    top = max(int(res.top.y_at(0.0)) if res.top is not None else 0, 0)
    bot = min(int(res.bottom.y_at(0.0)) if res.bottom is not None else H - 1, H - 1)
    xs = np.arange(int(np.ceil(x0)), int(x1))
    if bot - top < 10 or len(xs) == 0:
        return xs, np.zeros(len(xs))
    ys = np.arange(top, bot, 4)
    slope = statistics.median(v.slope for v in res.verticals)
    px = np.rint(W - 1 - (xs[None, :] + slope * (ys[:, None] - (top + bot) / 2.0))).astype(int)
    ok = (px >= 0) & (px < W)
    ink = np.where(ok, gray[ys[:, None], np.clip(px, 0, W - 1)] < ink_threshold, False)
    return xs, ink.mean(axis=0)


def _snap_target(res, gray, x, med, ink_threshold):
    """一条线就近该吸到哪：±SNAP_RULE 列宽内最高的淡界行细峰；没有就 ±SNAP_BLANK 列宽内最近的字间空白中点；都没有返回 None。"""
    xs, p = _profile(res, gray, x - SNAP_RULE * med - RULE_HALF, x + SNAP_RULE * med + RULE_HALF + 1, ink_threshold)
    best = None
    for i in range(RULE_HALF, len(xs) - RULE_HALF):
        v = p[i]
        if (v >= RULE_PEAK and abs(xs[i] - x) <= SNAP_RULE * med and v >= p[i - 1] and v >= p[i + 1]
                and p[i - RULE_HALF] < v / 2 and p[i + RULE_HALF] < v / 2 and (best is None or v > best[1])):
            best = (float(xs[i]), v)
    if best is not None:
        return best[0]
    runs, start = [], None
    for i, v in enumerate(p):
        if v < BLANK and start is None:
            start = i
        elif v >= BLANK and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(p) - 1))
    # 只认两头都落在窗口里的空白段（贴着窗口边的段量不出中点）
    mids = [(xs[a] + xs[b]) / 2.0 for a, b in runs if a > 0 and b < len(p) - 1]
    mids = [m for m in mids if abs(m - x) <= SNAP_BLANK * med]
    return float(min(mids, key=lambda m: abs(m - x))) if mids else None


def snap_lines(base, res, gray, *, leaf_layout: str = "single", ink_threshold: int = 128, rounds: int = 3):
    """在 `base`（网格或自由模式的网）上，把出带列两边的线逐轮吸到淡界行或字间空白中点上，直到列宽都进带。
    成了返回 (新网（`base` 的副本）, 吸过的线号)，不成返回 None。"""
    r = deepcopy(base)
    snapped: set[int] = set()
    xs0 = line_xs(res)
    med = statistics.median(_body_widths(xs0, leaf_layout))
    for _ in range(rounds):
        xs = line_xs(r)
        bad = out_of_band(xs, leaf_layout=leaf_layout)
        if not bad:
            return (r, snapped) if bad is not None else None
        moved = False
        for i in sorted({i for c in bad for i in (c - 1, c) if 0 <= i < len(xs)}):
            t = _snap_target(res, gray, xs[i], med, ink_threshold)
            if t is None or abs(t - xs[i]) < 2:
                continue
            d = t - xs[i]
            r.verticals[i] = replace(r.verticals[i], x_at_top=r.verticals[i].x_at_top + d)
            if len(r.verticals_straight) == len(r.verticals):
                r.verticals_straight[i] = replace(r.verticals_straight[i], x_at_top=r.verticals_straight[i].x_at_top + d)
            snapped.add(i)
            moved = True
        if not moved:
            return None
    return (r, snapped) if is_clean(line_xs(r), leaf_layout=leaf_layout) else None


def _frame_ridges(res, gray, xs, med, ink_threshold):
    """两侧外框线外 `FRAME_REACH` 列宽内的界行残段，按离外框线由近到远：(低侧, 高侧)。"""
    rs = _rule_ridges(res, gray, xs[0] - FRAME_REACH * med, xs[-1] + FRAME_REACH * med, RULE_RUN * med, ink_threshold)
    lo = sorted((r for r in rs if r < xs[0] - TOL), reverse=True)
    hi = sorted(r for r in rs if r > xs[-1] + TOL)
    return lo, hi


def snap_outer_to_frame(res, gray: np.ndarray, *, leaf_layout: str = "single", ink_threshold: int = 128) -> bool:
    """出带的外列偏窄、外侧有版框残段：外框线平移到最近那条残段上。新网干净才改 `res` 返回 True。"""
    xs = line_xs(res)
    med = statistics.median(_body_widths(xs, leaf_layout))
    bad = out_of_band(xs, leaf_layout=leaf_layout) or set()
    lo, hi = _frame_ridges(res, gray, xs, med, ink_threshold)
    v, vs = list(res.verticals), list(res.verticals_straight)
    filled = list(res.vline_filled) or [False] * len(v)
    moved = False
    for idx, col, width, ridges in ((0, 1, xs[1] - xs[0], lo), (len(xs) - 1, len(xs) - 1, xs[-1] - xs[-2], hi)):
        if col not in bad or width >= OUTER[0] * med or not ridges:
            continue
        d = ridges[0] - xs[idx]
        v[idx] = replace(v[idx], x_at_top=v[idx].x_at_top + d)
        if len(vs) == len(v):
            vs[idx] = replace(vs[idx], x_at_top=vs[idx].x_at_top + d)
        filled[idx] = False
        moved = True
    if not moved or not is_clean(line_xs(replace(res, verticals=v)), leaf_layout=leaf_layout):
        return False
    res.verticals, res.verticals_straight, res.vline_filled = v, vs, filled
    return True


def drops_framed_col(res, gray, new_xs, *, leaf_layout: str = "single", ink_threshold: int = 128) -> bool:
    """新网把贴着版框的旧外列整列甩出去了？旧外列外侧 `FRAME_REACH` 列宽内有界行残段（版框）＝这列在框里、是真列。"""
    xs = line_xs(res)
    med = statistics.median(_body_widths(xs, leaf_layout))
    lo, hi = _frame_ridges(res, gray, xs, med, ink_threshold)
    return bool((lo and new_xs[0] > (xs[0] + xs[1]) / 2.0) or (hi and new_xs[-1] < (xs[-2] + xs[-1]) / 2.0))


def rescue(res, gray: np.ndarray, detect_grid, *, leaf_layout: str = "single",
           ink_threshold: int = 128) -> tuple[object, str | None]:
    """`detect_grid(pitch)` 用网格模式重探（pitch＝本页中位列宽，书上有列距先验时调用方可以不用它）。
    返回 (结果, 用了哪条路 'frame'|'grid'|'extend'|'fuse'|'snap'|None)。没触发或都不接受就原样返回、路为 None。"""
    xs = line_xs(res)
    if not needs_rescue(xs, leaf_layout=leaf_layout):
        return res, None
    if snap_outer_to_frame(res, gray, leaf_layout=leaf_layout, ink_threshold=ink_threshold):
        return res, "frame"
    bad = out_of_band(xs, leaf_layout=leaf_layout)
    g = detect_grid(statistics.median(_body_widths(xs, leaf_layout)))
    gx = line_xs(g)

    def keeps_frame(new_xs):
        return not drops_framed_col(res, gray, new_xs, leaf_layout=leaf_layout, ink_threshold=ink_threshold)
    med = statistics.median(_body_widths(xs, leaf_layout))
    ridges = _rule_ridges(res, gray, xs[0] - TOL, xs[-1] + TOL, RULE_RUN * med, ink_threshold)
    if (len(gx) >= len(xs) and is_clean(gx, leaf_layout=leaf_layout)
            and n_shared(gx, xs) * 2 >= len(xs) and keeps_good_lines(xs, gx, bad, ridges=ridges) and keeps_frame(gx)):
        return g, "grid"
    r = deepcopy(res)
    if drop_and_extend(r, gray, leaf_layout=leaf_layout, ink_threshold=ink_threshold) and keeps_frame(line_xs(r)):
        return r, "extend"
    r = deepcopy(res)
    if (len(gx) == len(xs) and fuse(r, g, gray, bad, leaf_layout=leaf_layout, ink_threshold=ink_threshold)
            and keeps_frame(line_xs(r))):
        return r, "fuse"
    for base in ((g, res) if len(gx) >= len(xs) else (res,)):
        out = snap_lines(base, res, gray, leaf_layout=leaf_layout, ink_threshold=ink_threshold)
        if out is None:
            continue
        r, snapped = out
        rx = line_xs(r)
        # 列宽合格的列两边的线照样不许动（`keeps_good_lines`），除非是这一路从它吸到界行／空白上的
        # （vol29 p28：末列的「外框」是字边，真框淡）；网格自己挪开的线不豁免（vol13 p46）
        bx = line_xs(base)
        movable = {i for c in bad for i in (c - 1, c)}
        movable |= {j for j, x in enumerate(xs) if any(abs(x - bx[i]) <= TOL for i in snapped)}
        keeps = all(any(abs(x - y) <= TOL for y in rx) for j, x in enumerate(xs) if j not in movable)
        if n_shared(rx, xs) * 2 >= len(xs) and keeps_frame(rx) and keeps:
            return r, "snap"
    return res, None
