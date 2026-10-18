# -*- coding: utf-8 -*-
"""量横长短后端（`open_guji_cv/groups/bars.py`）。自造字块图（两横一竖），不读真书。"""
from __future__ import annotations

import numpy as np
import pytest

from open_guji_cv.groups import JudgeInput, PatchUnavailable, window_from_text
from open_guji_cv.groups.bars import BarsImageBackend, bar_ratio


class _Spec:
    def __init__(self, id):
        self.id = id


def _glyph(top, bottom, gap_in_top=0):
    """100×110 白底；竖画居中，上横长 top、下横长 bottom（像素），可在上横中间留白缝。"""
    g = np.full((110, 100), 255, np.uint8)
    g[5:105, 46:54] = 0
    for y0, w in ((30, top), (92, bottom)):
        x0 = 50 - w // 2
        g[y0:y0 + 6, x0:x0 + w] = 0
    if gap_in_top:
        g[30:36, 36:40] = 255      # 上横左半留一道白缝
    return g


def _cell(img):
    return JudgeInput(id="c", ref=None, window=window_from_text("", ""), patch=lambda: img)


def test_ratio_and_pick_ts():
    b = BarsImageBackend()
    assert b.judge(_Spec("ts"), _cell(_glyph(40, 80))).char == "土"
    assert b.judge(_Spec("ts"), _cell(_glyph(80, 40))).char == "士"
    assert b.judge(_Spec("wm"), _cell(_glyph(40, 80))).char == "未"
    assert b.judge(_Spec("wm"), _cell(_glyph(80, 40))).char == "末"


def test_close_ratio_abstains():
    v = BarsImageBackend().judge(_Spec("ts"), _cell(_glyph(60, 62)))
    assert v.char is None and v.why == "abstain:close"


def test_gap_in_bar_does_not_shorten_it():
    # 上横被白缝断开，量的是带内最左到最右，仍应是上横长
    assert bar_ratio(_glyph(80, 40, gap_in_top=1)) < 1


def test_no_bars_abstains_and_missing_patch_raises():
    blank = np.full((100, 100), 255, np.uint8)
    assert BarsImageBackend().judge(_Spec("ts"), _cell(blank)).char is None
    with pytest.raises(PatchUnavailable):
        BarsImageBackend().judge(_Spec("ts"), JudgeInput(id="c", ref=None, window=window_from_text("", "")))


def test_unknown_group_abstains():
    assert BarsImageBackend().judge(_Spec("jys"), _cell(_glyph(40, 80))).char is None
