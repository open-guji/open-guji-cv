# -*- coding: utf-8 -*-
"""书名列候选 `layout_title_fit`（row_segment 书级开关，缺省关）：认书名列、按字缝落格线、出候选格线。数据现造。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.steps.row_segment import RowSegmentParams, _title_fit_bounds, _title_gap_cuts, _title_run


def test_title_run_needs_title_then_notes():
    lay = {"notes": [6, 7]}
    assert _title_run(lay, {3, 4, 5, 6, 7}) == (3, 7)
    assert _title_run(lay, {3, 4, 6, 7}) is None                 # 中间断开
    assert _title_run({"notes": [4, 6]}, {3, 4, 5, 6}) is None    # 小注夹在正文中间
    assert _title_run({"notes": [6, 7]}, {5, 6, 7}) is None       # 书名不到 2 格
    assert _title_run({"notes": [6, 7], "raised": 1}, {3, 4, 5, 6, 7}) is None
    assert _title_run({}, {3, 4, 5}) is None                      # 没有小注：不是书名列


def test_gap_cuts_pick_wide_gaps_not_inner_gaps():
    """三字，每字 80 行、字里各有一道 3 行小白缝，字间 14 行白：格线落在字间缝正中，不进字里的小缝。"""
    has = []
    for i in range(3):
        has += [True] * 40 + [False] * 3 + [True] * 37
        if i < 2:
            has += [False] * 14
    pitch = len(has) / 3
    cuts = _title_gap_cuts(np.array(has), 3, pitch)
    assert cuts is not None and len(cuts) == 2
    assert abs(cuts[0] - 87.0) <= 1 and abs(cuts[1] - 181.0) <= 1


def test_gap_cuts_none_when_not_enough_gaps():
    assert _title_gap_cuts(np.array([True] * 100), 3, 33.0) is None


def test_title_fit_bounds_compressed_title():
    """页级格高 100，第 3–7 格是书名＋小注，但这一列刻得紧（字距 90）：候选格线跟着本列字缝走。"""
    period = 100.0
    img = np.full((2200, 60), 255, np.uint8)
    top = 300
    for i in range(5):
        y = top + i * 90
        img[y + 8:y + 80, 15:45] = 0
    lay = {"notes": [6, 7]}
    b = _title_fit_bounds(img, lay, {3, 4, 5, 6, 7}, 21, 0, (0, 60), 100.0, 2200.0, period, 128)
    assert b is not None and len(b) == 22
    assert abs(b[2] - (top + 8)) <= 1                  # 书名段从墨的起点起
    for i, y in enumerate(b[3:7]):                      # 段里的格线落在字缝（字底 +80 到下一字顶 +98）正中
        assert abs(y - (top + i * 90 + 89)) <= 1, (i, y)
    assert abs(b[7] - (top + 4 * 90 + 80)) <= 1         # 到墨的止点
    assert abs(b[1] - b[2] - (-period)) <= 1 and abs(b[8] - b[7] - period) <= 1   # 段外照页级格高


def test_param_dump_omits_switch_when_off():
    assert "layout_title_fit" not in RowSegmentParams().model_dump()
    assert RowSegmentParams(layout_title_fit=True).model_dump()["layout_title_fit"] is True
