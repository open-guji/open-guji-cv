# -*- coding: utf-8 -*-
"""Step0 反色带候选 `invert_detect`：判据「界行翻白」。数据全在这里现造。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.steps.invert_detect import detect_inverted

RULES = [300, 480, 660, 840, 1020]   # 界行 x（5 像素宽）


def _page(h=900, w=1300):
    g = np.full((h, w), 255, np.uint8)
    for x in RULES:
        g[100:800, x:x + 5] = 0
    return g


def _invert(g, y0, y1, x0, x1):
    g[y0:y1 + 1, x0:x1 + 1] = 255 - g[y0:y1 + 1, x0:x1 + 1]


def test_band_where_rule_lines_turn_white_is_a_candidate():
    g = _page()
    _invert(g, 400, 430, 250, 1100)              # 横带翻转：纸成黑、界行成白
    got = detect_inverted(g)
    assert len(got) == 1
    b = got[0]
    assert abs(b.bbox[1] - 400) <= 3 and abs(b.bbox[3] - 430) <= 3 and b.flipped_rules >= 4
    assert b.rule["kind"] in ("inverted_band", "inverted_rect")


def test_solid_black_bar_without_white_rules_is_not():
    g = _page()
    g[400:431, 250:1101] = 0                     # 实心粗线（版框、墨条）：界行在里面也是黑的
    assert detect_inverted(g) == []


def test_thin_frame_line_is_not():
    g = _page()
    _invert(g, 400, 406, 250, 1100)              # 7 行高：版框单线的粗细，不报
    assert detect_inverted(g) == []


def test_clean_page_has_none():
    assert detect_inverted(_page()) == []
