"""列距救援（Step1 后处理，2026-10-23 sheldon 定缺省开）：自由模式探出的列网里有列宽出了「列宽带」（殿本列宽极一致），
按「列距均匀」重定这一页的竖线。

**病**（殿本 vol11–20 v0.5.9 九页：vol13 p75、vol14 p103/186、vol16 p8/120、vol19 p29/86、vol20 p68/113）：
自由模式在某一列里多挑了一条假竖线（字心、夹注缝），把一列劈成两窄列；凑够 `expected_cols+1` 条线，
外侧真列的那条外框线就挤掉了——**一整列落在网外，字悄悄丢了**，后面列号全错一位。

**做法**（两条路，都只在页上有列宽出带时才走；正常页逐字节不变）：
1. 网格模式重探（`column_grid`，版框定死、列距均匀）；
2. 网格选不出版框对时（外框只有粗外条、不在候选池里）：去掉劈开窄对的那条线，在墨多的一侧
   按中位列距补一条外框线（记成插值线）。

**接受条件**：新列网每条正文列都在列宽带内，且至少一半的线与原线重合（±`tol` px）
——防止网格模式在卷端大印页、书名页上挑出另一套网（vol20 p179）。不满足就原样返回。

纯几何，不改 `border_geometry`（那是三个步骤的 `code_deps`）。
"""
from __future__ import annotations

import statistics
from dataclasses import replace

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


def keeps_good_lines(old, new, bad_cols, tol: float = TOL) -> bool:
    """列宽合格的列，两边的界行不许动：旧线里不挨着出带列的，新网里都得有（±tol）。
    防止网格模式把印得好好的界行挪到空白里（vol13 p46：外列偏宽 1.3，网格把内部三条真界行各挪 9px）。"""
    movable = {i for c in bad_cols for i in (c - 1, c)}
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


def rescue(res, gray: np.ndarray, detect_grid, *, leaf_layout: str = "single",
           ink_threshold: int = 128) -> tuple[object, str | None]:
    """`detect_grid(pitch)` 用网格模式重探（pitch＝本页中位列宽，书上有列距先验时调用方可以不用它）。
    返回 (结果, 用了哪条路 'grid'|'extend'|None)。没触发或都不接受就原样返回、路为 None。"""
    xs = line_xs(res)
    if not needs_rescue(xs, leaf_layout=leaf_layout):
        return res, None
    bad = out_of_band(xs, leaf_layout=leaf_layout)
    g = detect_grid(statistics.median(_body_widths(xs, leaf_layout)))
    gx = line_xs(g)
    if (len(gx) == len(xs) and is_clean(gx, leaf_layout=leaf_layout)
            and n_shared(gx, xs) * 2 >= len(xs) and keeps_good_lines(xs, gx, bad)):
        return g, "grid"
    if drop_and_extend(res, gray, leaf_layout=leaf_layout, ink_threshold=ink_threshold):
        return res, "extend"
    return res, None
