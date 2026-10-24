# -*- coding: utf-8 -*-
"""Step0 反色带候选 `invert_detect`：判据「界行翻白」。数据全在这里现造。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.steps.invert_detect import detect_inverted
from open_guji_cv.utils.preclean import apply_preclean, rule_mask

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
    assert b.rule["kind"] == "inverted_poly"
    fixed = apply_preclean(g, [b.rule], gate=False)[0]
    assert (fixed[395:436, 245:1106] == _page()[395:436, 245:1106]).mean() > 0.99   # 修回去了


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


def test_top_frame_under_blank_margin_is_not():
    g = _page()
    _invert(g, 100, 130, 250, 1100)              # 页顶：黑条上方是空白天头（外框），不报
    assert detect_inverted(g) == []


def test_bar_on_patterned_cover_is_not():
    g = _page()
    rng = np.random.default_rng(0)
    g[200:700] = np.where(rng.random((500, g.shape[1])) < 0.5, 0, 255).astype(np.uint8)
    g[400:431] = 255
    for x in RULES:
        g[400:431, x:x + 5] = 0
    _invert(g, 400, 430, 250, 1100)              # 满纸花纹（封面、书衣）里的黑条，不报
    assert detect_inverted(g) == []


def test_bottom_frame_over_blank_margin_is_not():
    g = _page()
    _invert(g, 770, 800, 250, 1100)              # 页底：黑条下方是空白地脚（下边框），不报
    assert detect_inverted(g) == []


def test_stepped_band_is_followed_not_boxed():
    g = _page()
    _invert(g, 400, 440, 250, 660)               # 左半带
    _invert(g, 420, 470, 661, 1100)              # 右半带低一截：台阶形
    got = detect_inverted(g)
    assert got and all(b.rule["kind"] == "inverted_poly" for b in got)
    m = np.zeros(g.shape, bool)
    for b in got:
        m |= rule_mask(g, b.rule)
    want = np.zeros(g.shape, bool)
    want[400:441, 250:661] = True
    want[420:471, 661:1101] = True
    assert (m & want).sum() / (m | want).sum() > 0.95


def test_two_strips_of_one_band_are_not_inverted_twice():
    g = _page()
    _invert(g, 400, 440, 250, 660)
    _invert(g, 420, 470, 661, 1100)
    got = detect_inverted(g)
    fixed = apply_preclean(g, [b.rule for b in got], gate=False)[0]
    assert (fixed[380:490, 240:1110] == _page()[380:490, 240:1110]).mean() > 0.98
