"""列宽均匀拟合（Step1 后处理）：自由模式探出的列网里有列宽出了带，就在候选线里一次挑出一串列宽全在带里的线。

**2.1（2026-11-04，border_detect 1.19）**：第一遍拟不出时，投影减本页底色（`FLOOR_PCT` 分位）再扣墨、找空白，
重拟一次（满页霉点的 vol43 p1：真线都被扣成负分，DP 无解，只剩 8 列）。第一遍拟得出的页不变。

**2.0（2026-11-03，border_detect 1.16）**：原来的 7 路救援（frame／grid／extend／fuse／snap／pad 及 1.15 的放宽）
并成一路——`seg/columns.fit_columns` 的 DP。各路当年救的页型都还在测试里（`tests/test_pitch_rescue.py`），
现在它们只是候选和打分的不同：

| 候选 | 分 | 当年对应哪一路 |
|---|---|---|
| 自由模式的线 | 3（附近有界行残段）／2 | 原线 |
| 网格模式的线（自由线范围内；网格与自由线重合过半时外侧也收） | 1.5／1 | grid、fuse |
| 界行残段（竖墨线连续 ≥ 0.8 列宽，含外侧 1.3 列宽内的版框） | 1 | frame、fuse（vol16 p8 天头残段） |
| 淡界行细峰、字间空白中点 | 0.5 | snap（vol48 p121 淡界行、vol44 p108 字心假线） |
| 原线按列距推一列、落在附近最空处（±`STEP_REACH` 列距） | 0.5 | snap 的 `_pitch_guess`（vol16 p6 界行淡到投影里没峰） |
| 有字一侧按列距外推的外框线（出图边截到图边） | 0 | extend、fuse（vol14 p186、vol86 p151） |
| 外列补到一个列距、外侧空白（版框没印出来） | 0 | pad（全唐文 07 p47） |

每条候选再扣墨（`INK_W`×min(两侧墨 `flank_ink`, 线上墨 `core_ink`)）：字心里的假线线上压着笔画、两侧都是字，
扣到负分就不进池；真界行（线上有墨、两侧空）和没印出的界行（落在字缝、线上空）都不扣。DP 求总分最高的一串，
另减 Σ|列宽/列距−1| 作平手判据（列宽越匀越好）。

**护栏**（原样保留，都是真页教训）：
- 新网至少一半的线与原线重合（±TOL），防在卷端大印页、书名页上挑出另一套网（vol20 p179）；
- 列宽合格的列两边、附近有界行残段的旧线不许动（vol13 p46：网格把三条真界行各挪 9px）；
- 外侧贴版框（外侧半列宽内有残段）的旧外列不许甩出网（vol40 p14、vol46 p118/p148：外推进版心条、整网平移一列）；
  外列偏宽、旧外框线本身压在残段上就不许往里挪（vol13 p46：外列偏宽是版框本来就宽，不是线错）。

正常页（列宽都在带里）不走这里，产物逐字节不变。纯几何，不改 `border_geometry`。
"""
from __future__ import annotations

import statistics
from dataclasses import replace

import numpy as np

from ...seg.columns import (Cand, ColumnSpec, blank_mids, check_columns, core_ink, fit_columns, flank_ink,
                            ink_profile, rule_ridges, thin_peaks)
from .column_pair_merge import line_xs
from .column_types import classify_columns

TOL = 8.0
#: 补外框那一侧要有字：墨像素占比下限（按二值图量，殿本正文列约 0.08–0.15，空白列 < 0.01）
MIN_INK = 0.02
BLANK = 0.01
#: 界行残段：一条竖向墨线连续 ≥ 此比例 × 列距（容 3px 断口）。字的竖笔不过一格高（殿本 ≤ 0.67 列宽）
RULE_RUN = 0.8
#: 外框保护：外侧这么宽（× 列距）以内有界行残段＝外列贴着版框
FRAME_REACH = 0.5
#: 候选窗口：原线两侧各这么宽（× 列距）。外列被劈半时真版框离原外框线 0.6–0.7 列宽（vol73 p110、vol94 p123）
REACH = 1.3
#: 外列补宽（pad）：新外框线外侧这么宽（× 列距）里得是空白
PAD_MARGIN = 0.3
#: 两侧墨的扣分系数：字心假线两侧墨占比 0.1–0.3，扣 1–3 分
INK_W = 8.0
#: 借形状的自由线斜率与本页中位斜率之差上限
SLOPE_TOL = 0.01

#: 按列距推线：推到的位置两侧这么宽（× 列距）里找投影最空处
STEP_REACH = 0.1
#: 本页底色：第一遍拟不出时，投影先减去这一分位再扣墨、找空白，重拟一次。满页霉点／污渍的页字缝里也有
#: 0.05–0.1 的墨，不减的话每条真线都被扣成负分、进不了池，DP 无解（vol43 p1 卷首页，2.1）
FLOOR_PCT = 20

SCORE_FREE, SCORE_FREE_RULE = 2.0, 3.0
SCORE_GRID, SCORE_GRID_RULE = 1.0, 1.5
SCORE_RIDGE, SCORE_BLANK, SCORE_STEP, SCORE_EXTRAP = 1.0, 0.5, 0.5, 0.0


def _skip(xs, leaf_layout):
    return {c.col for c in classify_columns(xs, leaf_layout=leaf_layout) if c.kind != "body"}


def check(xs, spec: ColumnSpec = ColumnSpec(), *, leaf_layout: str = "single"):
    """本页列宽检查（`seg/columns.check_columns`，版心／贴页边的 edge 列不受带约束）。"""
    return check_columns(xs, spec, skip=_skip(xs, leaf_layout))


def n_shared(a, b, tol: float = TOL) -> int:
    return sum(1 for x in a if any(abs(x - y) <= tol for y in b))


def keeps_good_lines(old, new, bad_cols, tol: float = TOL, ridges=None) -> bool:
    """列宽合格的列两边的旧线，新网里都得有（±tol）。给了 `ridges` 就只护附近有界行残段的旧线（没残段的线是
    自由模式探进字里的，列宽碰巧合格也不算真界行：换图源 vol40 新 p1 卷首大印页）。"""
    movable = {i for c in bad_cols for i in (c - 1, c)}
    if ridges is not None:
        movable |= {i for i, x in enumerate(old) if not any(abs(x - r) <= tol for r in ridges)}
    return all(any(abs(x - y) <= tol for y in new) for i, x in enumerate(old) if i not in movable)


def _straight(r):
    return list(r.verticals_straight) if len(r.verticals_straight) == len(r.verticals) else list(r.verticals)


def rescue(res, gray: np.ndarray, detect_grid, *, leaf_layout: str = "single", ink_threshold: int = 128,
           spec: ColumnSpec = ColumnSpec()) -> tuple[object, str | None]:
    """`detect_grid(pitch)` 用网格模式重探。返回 (结果, 'fit'|None)。列宽都在带里、正文列太少不判、或拟合不出／
    不过护栏时原样返回、None。

    先按原投影拟合；拟不出再减本页底色（`FLOOR_PCT` 分位）重拟一次。第一遍拟得出的页结果与 2.0 逐位相同。"""
    if spec.uniform != "strict":
        return res, None
    xs = line_xs(res)
    chk = check(xs, spec, leaf_layout=leaf_layout)
    if chk.ok:
        return res, None
    grids: dict = {}

    def grid_once(p):
        if p not in grids:
            grids[p] = detect_grid(p)
        return grids[p]
    for floor in (None, FLOOR_PCT):
        out, how = _fit(res, gray, grid_once, xs, chk, spec, ink_threshold, floor)
        if how:
            return out, how
    return res, None


def _fit(res, gray, detect_grid, xs, chk, spec: ColumnSpec, ink_threshold: int, floor_pct):
    pitch = chk.pitch
    H, W = gray.shape[:2]
    top = float(res.top.y_at(0.0)) if res.top is not None else 0.0
    bot = float(res.bottom.y_at(0.0)) if res.bottom is not None else float(H - 1)
    slope = statistics.median(v.slope for v in res.verticals)
    wx0, wx1 = max(xs[0] - REACH * pitch, 0.0), min(xs[-1] + REACH * pitch, float(W))
    px, prof = ink_profile(gray, top, bot, slope, wx0, wx1, ink_threshold=ink_threshold)
    if floor_pct is not None and len(prof):
        prof = np.clip(prof - np.percentile(prof, floor_pct), 0.0, None)
    ridges = rule_ridges(gray, top, bot, slope, wx0, wx1, RULE_RUN * pitch, ink_threshold=ink_threshold)

    def ink(a, b):
        a, b = min(a, b), max(a, b)
        sel = (px >= a + (b - a) / 6) & (px < b - (b - a) / 6)
        return float(prof[sel].mean()) if sel.any() else 0.0

    def penalty(x):
        # 字心假线：线上压着笔画、两侧也是字，两样都高才扣。真界行线上有墨但两侧空；没印出的界行落在字缝，
        # 线上空、两侧却可能贴着字（密排小字页 vol16 p6）——取两者小的
        return INK_W * min(flank_ink(px, prof, x), core_ink(px, prof, x))

    def near_rule(x):
        return any(abs(x - r) <= TOL for r in ridges)

    shape = [i for i, v in enumerate(res.verticals) if abs(v.slope - slope) <= SLOPE_TOL] or list(range(len(xs)))
    straight = _straight(res)

    def shifted(x, filled):
        j = min(shape, key=lambda i: abs(xs[i] - x))
        d = x - xs[j]
        return (replace(res.verticals[j], x_at_top=res.verticals[j].x_at_top + d),
                replace(straight[j], x_at_top=straight[j].x_at_top + d), filled)

    cands: list[Cand] = []

    def add(x, score, payload):
        if score >= 0 and 0 <= x <= W - 1 and all(abs(x - c.x) > TOL for c in cands):
            cands.append(Cand(x, score, payload))

    for x, v, s in zip(xs, res.verticals, straight):
        add(x, (SCORE_FREE_RULE if near_rule(x) else SCORE_FREE) - penalty(x), (v, s, False))
    g = detect_grid(pitch)
    gx = line_xs(g)
    g_same = n_shared(gx, xs) * 2 >= len(xs)
    for x, v, s in zip(gx, g.verticals, _straight(g)):
        if xs[0] < x < xs[-1] or g_same:
            add(x, (SCORE_GRID_RULE if near_rule(x) else SCORE_GRID) - penalty(x), (v, s, False))
    for r in ridges:
        add(r, SCORE_RIDGE - penalty(r), shifted(r, False))
    for m in thin_peaks(px, prof):
        add(m, SCORE_BLANK - penalty(m), shifted(m, False))
    for m in blank_mids(px, prof, blank=BLANK):
        add(m, SCORE_BLANK - penalty(m), shifted(m, False))
    for x in xs:                                                      # 按列距推一列，落到附近最空处
        for t in (x - pitch, x + pitch):
            sel = (px >= t - STEP_REACH * pitch) & (px <= t + STEP_REACH * pitch)
            if xs[0] < t < xs[-1] and sel.any():
                m = float(px[sel][np.argmin(prof[sel])])
                add(m, SCORE_STEP - penalty(m), shifted(m, False))
    for sign, outer, inner in ((-1, xs[0], xs[1]), (1, xs[-1], xs[-2])):
        edge = 0.0 if sign < 0 else float(W - 1)
        ext = outer + sign * min(pitch, abs(edge - outer))           # 有字一侧外推一列（出图边截到图边）
        if ink(outer, ext) >= MIN_INK:
            add(ext, SCORE_EXTRAP, shifted(ext, True))
        pad = inner + sign * pitch                                   # 外列补到一个列距、外侧空白
        if (abs(pad - outer) > TOL and ink(outer, pad) >= MIN_INK
                and 0 <= pad + sign * PAD_MARGIN * pitch <= W - 1
                and ink(pad, pad + sign * PAD_MARGIN * pitch) < BLANK):
            add(pad, SCORE_EXTRAP, shifted(pad, True))

    # 外侧贴版框的旧外列不许甩出网；外列偏宽、旧外框线本身压在版框残段上，就不许往里挪（偏窄的不护：
    # 双栏版框内外两道线之间被当成一列，vol94 p159）
    def bound(outer, inner, sign):
        if near_rule(outer) and abs(outer - inner) > pitch:
            return outer - sign * TOL
        if any(TOL < sign * (r - outer) <= FRAME_REACH * pitch for r in ridges):
            return (outer + inner) / 2.0
        return None
    n = max(len(xs), len(gx))
    chain = fit_columns(cands, n, pitch, spec,
                        first_max=bound(xs[0], xs[1], -1), last_min=bound(xs[-1], xs[-2], 1))
    if chain is None:
        return res, None
    new_xs = [c.x for c in chain]
    if n_shared(new_xs, xs) * 2 < len(xs) or not keeps_good_lines(xs, new_xs, chk.bad, ridges=ridges):
        return res, None
    out = replace(res, verticals=[c.payload[0] for c in chain],
                  verticals_straight=[c.payload[1] for c in chain],
                  vline_filled=[c.payload[2] for c in chain])
    return out, "fit"
