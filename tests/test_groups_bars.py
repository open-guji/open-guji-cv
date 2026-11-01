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


# —— 一二数横（yr，2026-10-25） ——

from open_guji_cv.groups.bars import count_bars  # noqa: E402


def _bars(*rows, h=40, w=120):
    """白底字块，每条横 (y0, 厚, x0, x1)，右端加一个顿笔小三角。"""
    g = np.full((h, w), 255, np.uint8)
    for y0, t, x0, x1 in rows:
        g[y0:y0 + t, x0:x1] = 0
        g[max(0, y0 - 3):y0 + t + 2, x1 - 8:x1] = 0
    return g


def test_count_one_and_two():
    assert count_bars(_bars((15, 8, 4, 116))) == ("一", "one")
    assert count_bars(_bars((8, 7, 30, 90), (60, 8, 4, 116), h=80)) == ("二", "two")


def test_two_with_broken_bottom_still_two():
    g = _bars((8, 7, 30, 90), (60, 8, 4, 116), h=80)
    g[60:68, 50:54] = 255                     # 下横断一道缝
    assert count_bars(g)[0] == "二"


def test_fragment_with_middle_tick_abstains():
    """「有」「六」「主」被切开的上半：一横中间竖起一笔（vol15:97:1:3、vol17:112:5:6）。"""
    g = _bars((26, 8, 4, 116), h=40)
    g[4:26, 56:64] = 0
    assert count_bars(g)[0] is None


def test_one_plus_border_line_abstains():
    """列尾格：一＋贴底的细边框线（上重下轻）不当二。"""
    g = _bars((10, 9, 4, 104), h=60)
    g[57:59, 0:120] = 0
    assert count_bars(g)[0] is None


def test_top_off_center_and_noise_abstain():
    assert count_bars(_bars((8, 7, 0, 30), (60, 8, 4, 116), h=80))[0] is None      # 上横只在最左：邻字残笔
    rng = np.random.default_rng(0)
    g = _bars((15, 8, 4, 116), h=60)
    for _ in range(40):                                                           # 印章噪点
        y, x = rng.integers(28, 56), rng.integers(0, 114)
        g[y:y + 4, x:x + 5] = 0
    assert count_bars(g)[0] is None
    assert count_bars(np.full((40, 40), 255, np.uint8))[0] is None


# —— 十士数横（ss，2026-11-01） ——

from open_guji_cv.groups.bars import ss_count  # noqa: E402


def _cross(*bars, h=100, w=100):
    """竖画居中，横条 (y0, 厚, x0, x1)。"""
    g = np.full((h, w), 255, np.uint8)
    g[2:h - 2, 46:54] = 0
    for y0, t, x0, x1 in bars:
        g[y0:y0 + t, x0:x1] = 0
    return g


def test_ss_one_bar_is_shi10_two_bars_is_shi4():
    assert ss_count(_cross((30, 7, 4, 96))) == ("十", "one")
    assert ss_count(_cross((28, 6, 25, 75), (86, 7, 4, 96))) == ("士", "two")


def test_ss_one_bar_near_bottom_and_close_bars_abstain():
    assert ss_count(_cross((85, 7, 4, 96)))[0] is None                  # 横在底部：切碎的字
    assert ss_count(_cross((30, 6, 4, 96), (40, 6, 4, 96)))[0] is None  # 两横挤在一起
    assert ss_count(np.full((40, 40), 255, np.uint8))[0] is None
