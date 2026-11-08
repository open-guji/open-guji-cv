# -*- coding: utf-8 -*-
"""cell_shrink.inner_frame_snap：抹白起点落在线中间时，沿线往字那边补抹满宽残边行（`_snap_rows`）。数据现造。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.steps.cell_shrink import _snap_reach, _snap_rows


def _col(foot_wide: bool = False) -> np.ndarray:
    """60 宽列图：y 100–106 一道满宽内线（略斜）；线上方是字，竖笔压到线上。"""
    ink = np.zeros((140, 60), bool)
    for x in range(60):
        c = 100 + x // 30                     # 线左高右低一行
        ink[c:c + 7, x] = True
    ink[40:100, 28:33] = True                 # 竖笔
    if foot_wide:
        ink[92:96, 10:50] = True              # 字底一横（两头碰不到列边）
    return ink


def test_snap_lifts_to_line_top():
    ink = _col()
    start = np.array([104 + x // 30 for x in range(60)])      # 拟合线落低了 4 行：起点在线中间
    assert _snap_rows(ink, start, -1, 6) == 4


def test_snap_stops_at_char_foot():
    ink = _col(foot_wide=True)
    start = np.array([100 + x // 30 for x in range(60)])      # 起点正好在线上沿
    assert _snap_rows(ink, start, -1, 10) == 0               # 上面只有竖笔、字底一横，不抹


def test_snap_skips_thick_stroke_on_line():
    """字底一横（8 行厚、占线的 2/3）直接压在线上：连着的墨超过补抹上限，一行不补。"""
    ink = _col()
    for x in range(10, 50):
        c = 100 + x // 30
        ink[c - 8:c, x] = True
    start = np.array([102 + x // 30 for x in range(60)])
    assert _snap_rows(ink, start, -1, 6) == 0


def test_snap_dashed_line():
    """虚线：线只在一段段上有墨，残边按线自己的虚段比。"""
    ink = np.zeros((140, 60), bool)
    for x in range(60):
        if (x // 6) % 2 == 0:
            ink[100:107, x] = True
    start = np.full(60, 103)
    assert _snap_rows(ink, start, -1, 6) == 3


def test_snap_reach_off_by_default():
    class P:
        inner_frame_snap = False
    assert _snap_reach(P(), 111.0) == 0
    P.inner_frame_snap = True
    assert _snap_reach(P(), 111.0) == 4
