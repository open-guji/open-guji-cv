"""版框线的网格模式（列数已知、列距均匀 → 逐槽验线、缺槽补线）。

2026-10-30 切分模块化第 3 步：投影找峰、位置＋角度联合搜索、整页找竖线／上下框线这些通用部分拆进了
`open_guji_cv/seg/lines.py`，这里只留网格模式。网格模式先留在 `utils/`，等 `border_geometry` 里殿本那块
一起搬进套书目录（`border_geometry` 现在还在 `utils/`，从这里 import）。
"""

from __future__ import annotations

import numpy as np

from ..seg.lines import (
    DEFAULT_ALPHA,
    DEFAULT_HYST,
    LineMatch,
    _snap_to_inner_rule,
    _vline_pool,
    find_horizontal_border,
    joint_search_coarse_to_fine,
)


# ── 网格模式：列数已知、列距均匀 → 逐槽验线、缺槽补线 ──────────────────
# 北行日錄刻本（灰度扫描、筒子页 9+版心+9 = 19 列）实测：全书 972 个界行槽位里
# 120 个（12.3%）**根本没印出界行**（p41 左半叶整片空白，只有右半叶有线；54 页里
# 只有 15 页界行齐全）。自由模式按分数取前 N 条时，这些槽位只能拿字身竖向对齐的
# 假峰凑数（半高宽 50+px、分数 ~10），而 `expected_cols` 多写 1 又逼它每页收一条
# 页边。四庫總目那批是 1-bit 双色扫描，界行条条实黑，从来没有「槽位空着」这回事，
# 所以自由模式在 14 页金标上中位误差 0.05px——不是算法坏了，是这本书缺线。
#
# 网格模式的做法：版框两条线定死，列距 = 框宽 / (N−1)，每个槽位只在 ±GRID_SLOT_TOL
# 里做位置+角度联合精搜；找不到细线（分数低于 GRID_MIN_SCORE，或半高宽超过
# GRID_MAX_WIDTH）就按相邻已验线**线性插值**，并把该槽标成 filled。于是每条线要么是
# 验过的细线、要么是几何插值——永远不会落在字上。
#
# ⚠️ **下面四个数是在北行日錄刻本（2801×2343、框高 1482、列距 119）上标定的绝对像素**。
# 换一本分辨率差一倍的书，它们直接失效——而且**不会报错**，只会静默退化成
# 「整页插值」或「整页验不上」（跟 `top_band_frac` 那个坑同型）。
# `grid_thresholds()` 按 `col_pitch` / `frame_height` 把它们换算过去，新书用那个。
GRID_SLOT_TOL = 18       # px。p20/p41 实测等距网格离真线最多 7~9px，留一倍余量；
                         # 再大就够到字身边缘（栏缝约 40px 宽）。≈ col_pitch 的 15%
GRID_MIN_SCORE = 20.0    # 半高宽匹配分 = 沿线投影行数 / 半高宽，**跟框高成正比**。
                         # 同书实测：真界行 27~222、字身假峰 ~10、空槽 ~1。≈ 框高的 1.35%
GRID_MAX_WIDTH = 12.0    # 细线物理宽度，跟 dpi 成正比；字身假峰半高宽 50+。
                         # 与 INNER_WIDTH_MAX 同量级。≈ col_pitch 的 10%
GRID_PITCH_TOL = 0.08    # 版框对的隐含列距与 col_pitch 的容差（逐页列距实测 p10–p90 ±2%）。
                         # **无量纲，换书不用改**

# 标定基准：北行日錄刻本（`beixing-guben-workspace/books/bxgb.yaml`）。
# 改这几个数 = 改所有走网格模式的书，改完必须重跑两本书的回归。
GRID_REF_PITCH = 119.0        # 该书列距中位（54 页实测）
GRID_REF_FRAME_H = 1482.0     # 该书框高中位（54 页实测）


def grid_thresholds(col_pitch: float | None = None, frame_height: float | None = None
                    ) -> dict[str, float]:
    """把网格模式那三个绝对像素阈值按**本书的列距/ 框高**换算过去，
    返回可直接展开给 `find_vertical_lines_grid(**...)` 的 dict。

    `slot_tol` 与 `max_width` 跟**列距**成正比（都是横向物理尺度：栏缝宽、线宽），
    `min_score` 跟**框高**成正比（分数 = 沿线投影行数 / 半高宽，线越长分越高）。
    `pitch_tol_frac` 无量纲，不换算。缺哪个先验就保留哪一项的缺省值——
    给不出就退回北行日錄那组绝对值，跟不调用这个函数完全一样。

    ⚠️ **`frame_height` 只能由调用方传进来**：`find_vertical_lines*` 跑在
    `find_horizontal_border` **之前**（下版框救援要用竖线，顺序反不过来），
    这一步拿不到框高。`BookSpec.frame_height` 就是给这个用的，量法见
    `measure_book_frame_height()`。
    """
    out: dict[str, float] = {"pitch_tol_frac": GRID_PITCH_TOL}
    if col_pitch is not None and col_pitch > 0:
        k = col_pitch / GRID_REF_PITCH
        out["slot_tol"] = int(round(GRID_SLOT_TOL * k))
        out["max_width"] = GRID_MAX_WIDTH * k
    else:
        out["slot_tol"] = GRID_SLOT_TOL
        out["max_width"] = GRID_MAX_WIDTH
    if frame_height is not None and frame_height > 0:
        out["min_score"] = GRID_MIN_SCORE * (frame_height / GRID_REF_FRAME_H)
    else:
        out["min_score"] = GRID_MIN_SCORE
    return out


def measure_book_frame_height(masks: list[np.ndarray], band_frac: float | None = None
                              ) -> float | None:
    """整册「下版框 y − 上版框 y」的中位数，给 `grid_thresholds(frame_height=)` 用。
    跟 `measure_book_bottom_gap` 一样是**册级**统计——单页函数拿不到，只能由调用方
    按册算好传进来。一页都量不出来返回 None。"""
    vals = []
    kw = {} if band_frac is None else {"band_frac": float(band_frac)}
    for mask in masks:
        try:
            top = find_horizontal_border(mask, "top", **kw)
            bot = find_horizontal_border(mask, "bottom", **kw)
        except Exception:
            continue
        h = bot.position - top.position
        if h > 0:
            vals.append(float(h))
    return float(np.median(vals)) if vals else None


def is_thin_rule(r: LineMatch, min_score: float = GRID_MIN_SCORE,
                 max_width: float = GRID_MAX_WIDTH) -> bool:
    """这条候选是不是一条**细界行**（而不是粗外条 / 字身假峰）。

    网格模式里「哪些候选算数」只有这一处判据，选版框对和逐槽验线共用同一把尺子
    ——两处判据必须一致，否则会出现「支持数算它、验线不认它」的错位。
    """
    return 0.0 < r.width <= max_width and r.score >= min_score


def select_frame_pair(pool: list[LineMatch], n_lines: int, col_pitch: float | None = None,
                      *, slot_tol: int = GRID_SLOT_TOL, min_score: float = GRID_MIN_SCORE,
                      max_width: float = GRID_MAX_WIDTH,
                      pitch_tol_frac: float = GRID_PITCH_TOL,
                      min_dist: int = 60) -> tuple[LineMatch, LineMatch] | None:
    """从候选池里选出左右版框那一对。选不出来返回 None。

    候选池里两两配对，隐含列距 (b−a)/(n_lines−1) 与 `col_pitch` 差在 `pitch_tol_frac`
    内（没给 `col_pitch` 就只要求列距 ≥ `min_dist`）；按「有多少槽位落着细线」排，
    同分再按两条线的投影和排——版框是整页最实的两条竖线，页边那条假线
    （北行日錄 54/54 页都有）隐含列距不对、支持数也低，选不上。

    ⚠️ **不给 `col_pitch` 时这一步会挑到「一端是粗外条」的对**，隐含列距被拉伸。
    四庫總目 vol02/3（卷題頁）实测：真界行 9 条、列距 184，但页面最右只有粗外框
    （半高宽 17px，`_snap_to_inner_rule` 找不到细内框——这一页那侧确实没印内框），
    选中对 (343, 2035) 隐含列距 188，末两槽累计漂移 24/31px **超出 ±18px 的
    `slot_tol`**，第 9 槽验不上、插值落到「欽定四庫全書總目卷」那一列的字上。
    自由模式在同一页 10 条全对。所以**网格模式不是自由模式的超集**，
    带 `col_pitch` 先验（北行日錄 119±8%）时才拦得住。见 overview 仓
    `项目进展/图片初步数字化/进度/北行日录古本/03-竖线探测模块化.md` §A。
    """
    n_gap = n_lines - 1
    thin = [r for r in pool if is_thin_rule(r, min_score, max_width)]

    def support(a: LineMatch, b: LineMatch) -> int:
        p = (b.position - a.position) / n_gap
        return sum(1 for k in range(1, n_gap)
                   if any(abs(r.position - (a.position + k * p)) <= slot_tol for r in thin))

    best: tuple[tuple[int, float], LineMatch, LineMatch] | None = None
    for a in pool:
        for b in pool:
            span = b.position - a.position
            if span <= 0:
                continue
            p = span / n_gap
            if col_pitch is not None:
                if abs(p - col_pitch) > pitch_tol_frac * col_pitch:
                    continue
            elif p < min_dist:
                # 列距不可能小于候选 NMS 间距（相邻两条线本来就会被合掉）。
                # 别写成 2×min_dist：那会把 119px 的列距（北行日錄）直接拒掉。
                continue
            key = (support(a, b), a.proj + b.proj)
            if best is None or key > best[0]:
                best = (key, a, b)
    return None if best is None else (best[1], best[2])


def verify_slots(mask: np.ndarray, left: LineMatch, right: LineMatch, n_lines: int,
                 bank: tuple[int, dict[float, np.ndarray]] | None = None,
                 *, slot_tol: int = GRID_SLOT_TOL, min_score: float = GRID_MIN_SCORE,
                 max_width: float = GRID_MAX_WIDTH,
                 alpha: float = DEFAULT_ALPHA, hyst: int = DEFAULT_HYST
                 ) -> list[LineMatch | None]:
    """版框定死之后逐槽验线：返回长度 `n_lines` 的列表，验上的是 `LineMatch`、
    验不上的是 `None`（交给 `interpolate_missing` 补）。两端就是传进来的 `left`/`right`。

    每槽在 `left + k·pitch ± slot_tol` 里做位置+角度联合精搜（两翼都要干净），
    通过 `is_thin_rule` 才算探到。**逐槽精搜比整页投影灵敏得多**：北行日錄粗量
    120 个「空槽」里最后只有 7 个真的没线。

    ⚠️ 版框对若被拉伸（见 `select_frame_pair`），末几槽的累计漂移会超出 `slot_tol`，
    这里就会「明明有线却验不上」——症状在插值那一步才显出来，病因在选对那一步。
    """
    _, w = mask.shape
    n_gap = n_lines - 1
    pitch = (right.position - left.position) / n_gap
    lines: list[LineMatch | None] = [left] + [None] * (n_gap - 1) + [right]
    for k in range(1, n_gap):
        c = left.position + k * pitch
        lo, hi = max(0, int(round(c - slot_tol))), min(w - 1, int(round(c + slot_tol)))
        r = joint_search_coarse_to_fine(mask, "v", lo, hi, alpha=alpha, hyst=hyst,
                                        coarse_bank=bank, flank_sides="both")
        if is_thin_rule(r, min_score, max_width):
            lines[k] = r
    return lines


def interpolate_missing(lines: list[LineMatch | None]) -> tuple[list[LineMatch], list[bool]]:
    """把 `verify_slots` 留下的 `None` 按相邻已验线线性插值（位置和斜率都插），
    返回 (补齐的线, `filled` 标记)。插出来的线 `score/width/proj` 记 0——下游据此
    知道这条不是量到的。两端必须是已验线（`verify_slots` 保证）。"""
    n = len(lines)
    known = [i for i in range(n) if lines[i] is not None]
    if len(known) < 2:
        raise ValueError("interpolate_missing 需要至少两条已验线（两端版框）")
    out = list(lines)
    filled = [ln is None for ln in lines]
    for i in range(n):
        if out[i] is not None:
            continue
        j = max(x for x in known if x < i)
        k = min(x for x in known if x > i)
        lj, lk = out[j], out[k]
        t = (i - j) / (k - j)
        out[i] = LineMatch(position=lj.position + t * (lk.position - lj.position),
                           slope=lj.slope + t * (lk.slope - lj.slope),
                           score=0.0, width=0.0, proj=0.0)
    return [ln for ln in out if ln is not None], filled


def lattice_frame_pair(mask: np.ndarray, pool: list[LineMatch], n_lines: int, col_pitch: float,
                       bank: tuple[int, dict[float, np.ndarray]] | None = None,
                       *, slot_tol: int = GRID_SLOT_TOL, min_score: float = GRID_MIN_SCORE,
                       max_width: float = GRID_MAX_WIDTH,
                       pitch_tol_frac: float = GRID_PITCH_TOL,
                       alpha: float = DEFAULT_ALPHA, hyst: int = DEFAULT_HYST
                       ) -> tuple[LineMatch, LineMatch, bool, bool] | None:
    """版框对不在候选池里时，按细界行拟等距网格反推版框两端。返回
    `(左端, 右端, 左端是插值, 右端是插值)`，定不下来返回 None。

    1. 池里的细线（`is_thin_rule`）两两配对，隐含列距 dx/round(dx/col_pitch) 落在
       `col_pitch ± pitch_tol_frac` 内的，当一张候选网格（原点、列距）；数有多少条细线落在
       某个槽 ± `slot_tol` 内，取支持最多的（同分取残差和小的），再用支持线最小二乘重拟。
    2. 在这张网格上滑一个 `n_lines` 槽的窗口，两端都要落在图内；按「窗口里的支持线数、
       两端有没有支持线」排，**并列第一不止一个就返回 None**（宁可让闸1 拒，不猜）。
       支持线不到 `n_lines` 的一半也返回 None。
    3. 两端槽位各在 ± `slot_tol` 里做联合精搜（翼朝页心），过 `_snap_to_inner_rule`；
       搜到的线墨分不到 `min_score` 就按网格位置插一条（斜率取支持线中位），标插值。
    """
    h, w = mask.shape
    n_gap = n_lines - 1
    thin = sorted((r for r in pool if is_thin_rule(r, min_score, max_width)),
                  key=lambda r: r.position)
    if len(thin) < 2:
        return None
    xs = np.array([r.position for r in thin])

    best = None
    for i in range(len(thin)):
        for j in range(i + 1, len(thin)):
            dx = xs[j] - xs[i]
            k = int(round(dx / col_pitch))
            if k < 1:
                continue
            p = dx / k
            if abs(p - col_pitch) > pitch_tol_frac * col_pitch:
                continue
            ks = np.round((xs - xs[i]) / p)
            res = np.abs(xs - (xs[i] + ks * p))
            sup = res <= slot_tol
            key = (int(sup.sum()), -float(res[sup].sum()))
            if best is None or key > best[0]:
                best = (key, sup, ks)
    if best is None:
        return None
    _, sup, ks = best
    kk, xx = ks[sup], xs[sup]
    if len(set(kk.tolist())) >= 2:
        p, o = np.polyfit(kk, xx, 1)
    else:                                                   # 理论上到不了：至少两条支持线、不同槽
        return None
    k_sup = set(int(k) for k in kk)

    windows = []
    for s in range(min(k_sup) - n_gap, max(k_sup) + 1):
        lo, hi = o + s * p, o + (s + n_gap) * p
        if lo < 0 or hi > w - 1:
            continue
        inside = sum(1 for k in k_sup if s <= k <= s + n_gap)
        ends = int(s in k_sup) + int((s + n_gap) in k_sup)
        windows.append(((inside, ends), s))
    if not windows:
        return None
    windows.sort(reverse=True)
    if len(windows) > 1 and windows[0][0] == windows[1][0]:
        return None
    (inside, _), s = windows[0]
    if inside * 2 < n_lines:
        return None

    slope = float(np.median([r.slope for r, ok in zip(thin, sup) if ok]))

    def endpoint(c: float, center_side: str) -> tuple[LineMatch, bool]:
        lo_, hi_ = max(0, int(round(c - slot_tol))), min(w - 1, int(round(c + slot_tol)))
        r = joint_search_coarse_to_fine(mask, "v", lo_, hi_, alpha=alpha, hyst=hyst,
                                        coarse_bank=bank, flank_sides=center_side)
        r = _snap_to_inner_rule(mask, r, center_side, alpha, hyst)
        if r.score >= min_score and abs(r.position - c) <= slot_tol:
            return r, False
        return LineMatch(position=float(c), slope=slope, score=0.0, width=0.0, proj=0.0), True

    a, a_f = endpoint(o + s * p, "right")
    b, b_f = endpoint(o + (s + n_gap) * p, "left")
    return a, b, a_f, b_f


def find_vertical_lines_grid(mask: np.ndarray, n_lines: int, col_pitch: float | None = None,
                             *, slot_tol: int = GRID_SLOT_TOL, min_score: float = GRID_MIN_SCORE,
                             max_width: float = GRID_MAX_WIDTH,
                             pitch_tol_frac: float = GRID_PITCH_TOL,
                             min_dist: int = 60, nms_percentile: float = 90,
                             edge_margin: int = 200,
                             alpha: float = DEFAULT_ALPHA, hyst: int = DEFAULT_HYST,
                             lattice_fallback: bool = False
                             ) -> tuple[list[LineMatch], list[bool]]:
    """列数已知（`n_lines` = 列数 + 1）、列距均匀的页：返回恰好 `n_lines` 条线
    （按 x 升序）和同长度的 `filled` 标记（True = 该槽位没探到细线、按几何插值）。

    三步，各自是纯函数、可单独测/单独用：
    1. `select_frame_pair` 选版框对；
    2. `verify_slots` 逐槽验线；
    3. `interpolate_missing` 缺槽插值。

    ⚠️ `n_lines` 必须是这本书的真值——写错了网格整体错位，任何一槽都验不上，
    最后全靠插值（闸2 会看到列宽异常）。北行日錄刻本曾把 expected_cols 写成 20
    （实际 19），就是这种情况。

    ⚠️ **不是自由模式的超集**：没有 `col_pitch` 先验时 `select_frame_pair` 可能挑到
    被拉伸的版框对，反而不如自由模式（四庫總目 vol02/3 实测）。给**界行没印全**的书
    用，并且**务必配 `col_pitch`**。

    `lattice_fallback=True`（缺省关，关着逐位不变）：`select_frame_pair` 选不出版框对时，
    不退回截断，改走 `lattice_frame_pair`——按已探到的细界行拟一张等距网格、在图内框出
    `n_lines` 个槽，再照常逐槽验线、缺槽插值。用在版框那条线压根不在候选池里的页
    （殿本换源 vol12 p139：右版框贴图边、被边窗里的界行顶掉，左边带进邻叶版心）。
    """
    if n_lines < 2:
        raise ValueError(f"n_lines must be >= 2, got {n_lines}")
    pool, bank = _vline_pool(mask, min_dist, nms_percentile, edge_margin, alpha, hyst)
    if len(pool) < 2:
        pool.sort(key=lambda r: r.position)
        return pool, [False] * len(pool)

    pair = select_frame_pair(pool, n_lines, col_pitch, slot_tol=slot_tol,
                             min_score=min_score, max_width=max_width,
                             pitch_tol_frac=pitch_tol_frac, min_dist=min_dist)
    if pair is None and lattice_fallback and col_pitch is not None:
        lat = lattice_frame_pair(mask, pool, n_lines, col_pitch, bank, slot_tol=slot_tol,
                                 min_score=min_score, max_width=max_width,
                                 pitch_tol_frac=pitch_tol_frac, alpha=alpha, hyst=hyst)
        if lat is not None:
            a, b, a_filled, b_filled = lat
            lines = verify_slots(mask, a, b, n_lines, bank, slot_tol=slot_tol,
                                 min_score=min_score, max_width=max_width, alpha=alpha, hyst=hyst)
            out, filled = interpolate_missing(lines)
            filled[0], filled[-1] = a_filled, b_filled
            return out, filled
    if pair is None:
        # 没有任何一对满足列距约束——版框本身没探到，退回自由模式的截断，
        # 让闸1 按列数拒掉这一页
        pool = pool[:n_lines]
        pool.sort(key=lambda r: r.position)
        return pool, [False] * len(pool)

    a, b = pair
    a = _snap_to_inner_rule(mask, a, "right", alpha, hyst)
    b = _snap_to_inner_rule(mask, b, "left", alpha, hyst)
    lines = verify_slots(mask, a, b, n_lines, bank, slot_tol=slot_tol,
                         min_score=min_score, max_width=max_width, alpha=alpha, hyst=hyst)
    return interpolate_missing(lines)

