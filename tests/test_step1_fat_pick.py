# -*- coding: utf-8 -*-
"""Step1 竖线：候选名额被字身假峰占掉、真线漏在双倍宽缝里（overview#266，vol03 p49）。

`peak_line_search._repair_fat_pick` 只对这一种形态动。合成数据按 vol03 几何画：列距 180、线宽 4。"""

from __future__ import annotations

import numpy as np

from open_guji_cv.utils import peak_line_search as P

PITCH = 180


def _lm(pos, score=550.0, width=4.0):
    return P.LineMatch(position=float(pos), slope=0.0, score=score, width=width, proj=0.0)


def _mask_with_lines(xs):
    m = np.zeros((2400, 2200), np.float64)
    for x in xs:
        m[:, int(x) - 2:int(x) + 2] = 1.0
    return m


def test_fat_pick_is_swapped_for_the_line_in_the_double_gap():
    real = [100 + k * PITCH for k in range(10)]                  # 旧坐标（左原点）也无所谓，只看间距
    missing = real[3]
    mask = _mask_with_lines([x for x in real if x != missing])
    mask[:, missing - 1:missing + 1] = 1.0                       # 真线在，只是没进候选池
    picks = [_lm(x) for x in real if x != missing] + [_lm(real[7] + 90, score=15.0, width=74.0)]
    out = sorted(r.position for r in P._repair_fat_pick(mask, picks, P.DEFAULT_ALPHA, P.DEFAULT_HYST))
    assert len(out) == 10
    assert abs(out[3] - missing) <= 3
    assert all(abs(o - (real[7] + 90)) > 20 for o in out)


def test_fat_pick_left_alone_without_a_double_gap():
    real = [100 + k * PITCH for k in range(10)]
    mask = _mask_with_lines(real)
    picks = [_lm(x) for x in real[:9]] + [_lm(real[4] + 90, score=15.0, width=74.0)]
    out = P._repair_fat_pick(mask, picks, P.DEFAULT_ALPHA, P.DEFAULT_HYST)
    assert out is picks                                          # 没有双倍宽的缝：原样返回
