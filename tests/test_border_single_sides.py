# -*- coding: utf-8 -*-
"""四周單邊：册声明 frame_layers 左／右 = 1 时，该侧最外线不往页心换内框，也不量该侧外框（CV1 11-26，朱楓林集 p87）。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.seg.lines import find_vertical_lines

W, H = 1900, 1600


def _page(seed=0):
    """九列满字页；页右真版框＝粗条（x 1640–1660）；距粗条 ~50px 处一条穿字的断续假线。"""
    rng = np.random.default_rng(seed)
    m = np.zeros((H, W), dtype=np.float64)
    for x in range(250, 1500, 150):                 # 细界行
        m[100:1500, x - 2:x + 2] = 1
    m[100:1500, 1640:1660] = 1
    for c in range(100, 1650, 150):                 # 字
        for y in range(120, 1480, 60):
            for xx in (c + 30, c + 75, c + 110):
                if rng.random() < .8:
                    m[y:y + 40, xx - 12:xx + 12][rng.random((40, 24)) < .5] = 1
    for y in range(100, 1500, 40):                  # 假线
        m[y:y + 4, 1594:1597] = 1
    return m


def _last(**kw):
    return find_vertical_lines(_page(), expected_count=10, **kw)[-1]


def test_default_snaps_to_thin_line_inside_bar():
    assert _last().position < 1620                  # 旧行为：粗条换成了里面那条


def test_no_snap_right_keeps_bar():
    r = _last(no_snap=("right",))
    assert r.position > 1630 and r.width > 12


def test_no_snap_left_does_not_touch_right_side():
    assert _last(no_snap=("left",)).position == _last().position


def test_no_snap_empty_equals_default():
    a = find_vertical_lines(_page(), expected_count=10)
    b = find_vertical_lines(_page(), expected_count=10, no_snap=())
    assert [(r.position, r.slope, r.score) for r in a] == [(r.position, r.slope, r.score) for r in b]
