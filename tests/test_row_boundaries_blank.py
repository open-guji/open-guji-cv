"""弹性 DP 的两条新规则（2026-09-05，切线金标 250 条驱动）：

1. 空白格不吃间距下界：列里少一个字时，缺的那一格不该摊到邻字上（局部滑格）；
2. 列尾格按墨算高：尾部留白/残渣不该把倒数第二条格线挤进末字。

合成投影：字 = 一段墨（0.8·period 高，墨量 0.5·dst_w），缝 = 0 墨。
"""

from __future__ import annotations

import numpy as np

from open_guji_cv.utils.row_boundaries import fit_row_boundaries

PERIOD, DST_W = 110, 180


def _column(chars: list[bool], tail_blank: int = 0, head: int = 10) -> tuple[np.ndarray, list[int]]:
    """chars[i] = 该格有没有字。返回投影与"真缝"位置（每个字格的上边界）。"""
    h = head + PERIOD * len(chars) + tail_blank + 10
    proj = np.zeros(h, dtype=np.float64)
    gaps = []
    y = head
    for present in chars:
        gaps.append(y)
        if present:
            proj[y + 12:y + 12 + int(PERIOD * 0.8)] = 0.5 * DST_W
        y += PERIOD
    gaps.append(y)
    return proj, gaps


def _err(bounds, gaps):
    return [min(abs(b - g) for b in bounds) for g in gaps]


def test_regular_column_unchanged():
    proj, gaps = _column([True] * 21)
    r = fit_row_boundaries(proj, DST_W, border_top=0, border_bottom=len(proj) - 1, period=PERIOD, n_slots=21)
    assert r is not None
    assert max(_err(r.boundaries, gaps[1:-1])) <= 3


def test_missing_char_mid_column_does_not_shift_neighbors():
    """第 10 格空：旧 DP 把这一格摊给邻字（每条格线偏几十像素），新规则给它一个空白格。"""
    chars = [True] * 21
    chars[9] = False
    proj, gaps = _column(chars)
    r = fit_row_boundaries(proj, DST_W, border_top=0, border_bottom=len(proj) - 1, period=PERIOD, n_slots=21)
    assert r is not None
    # 除空格两侧外，其余真缝都要有格线落在 ±3px；空格只要求不把邻字切坏
    keep = [g for i, g in enumerate(gaps[1:-1], start=1) if i not in (9, 10)]
    assert max(_err(r.boundaries, keep)) <= 3, _err(r.boundaries, keep)


def test_trailing_blank_does_not_push_last_cut_into_last_char():
    """末字之后有 0.5·period 留白：倒数第二条格线仍该落在末字上方的真缝。"""
    proj, gaps = _column([True] * 21, tail_blank=int(PERIOD * 0.5))
    r = fit_row_boundaries(proj, DST_W, border_top=0, border_bottom=len(proj) - 1, period=PERIOD, n_slots=21)
    assert r is not None
    last_gap = gaps[-2]          # 末字上边界
    assert min(abs(b - last_gap) for b in r.boundaries[1:-1]) <= 3


def test_two_missing_chars_at_tail():
    """列尾少两个字：真缝全部命中，末两格是空白格。"""
    chars = [True] * 19 + [False, False]
    proj, gaps = _column(chars)
    r = fit_row_boundaries(proj, DST_W, border_top=0, border_bottom=len(proj) - 1, period=PERIOD, n_slots=21)
    assert r is not None
    assert max(_err(r.boundaries, gaps[1:19])) <= 3
    # 末字的下边界落在空白区里，那里只有每 20px 一个的合成候选，精度天然是半步（≤10px）
    assert _err(r.boundaries, gaps[19:20])[0] <= 10
