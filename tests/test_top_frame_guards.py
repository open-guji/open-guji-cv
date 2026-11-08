# -*- coding: utf-8 -*-
"""上版框两道护栏：Step1 `seg.lines._weak_top_guard`（选中的线太弱、上方有强横线就改取）与
Step2 `refine_top_by_frame` 否决例外 `_ink_between`（满宽段与 top_y 之间先白后字墨）。数据现造。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.books.siku_zongmu.column import _ink_between
from open_guji_cv.seg.lines import TOP_WEAK_RATIO, LineMatch, _weak_top_guard


def _page(weak_y: int = 150) -> np.ndarray:
    """1920×1000 页：y 60–71 粗框条满宽，weak_y 一条只占两成宽的细横墨（首行字顶）。"""
    m = np.zeros((1920, 1000))
    m[60:72, :] = 1.0
    m[weak_y:weak_y + 2, ::5] = 1.0
    return m


def _match(y: float) -> LineMatch:
    return LineMatch(position=y, slope=0.0, score=1.0, width=2.0, proj=1.0)


def test_weak_top_moves_up_to_strong_bar():
    r = _weak_top_guard(_page(), _match(150.0), 0, 288, TOP_WEAK_RATIO, 1.0, 2)
    assert 58 <= r.position <= 74


def test_weak_top_keeps_strong_line():
    r = _weak_top_guard(_page(), _match(65.0), 0, 288, TOP_WEAK_RATIO, 1.0, 2)
    assert r.position == 65.0


def test_weak_top_ignores_small_jump():
    """挪不到 0.021 页高（双边框里内外线之争）不动。"""
    r = _weak_top_guard(_page(weak_y=95), _match(95.0), 0, 288, TOP_WEAK_RATIO, 1.0, 2)
    assert r.position == 95.0


def test_ink_between_needs_blank_then_ink():
    blank, ink = [0.0] * 5, [0.2] * 25
    assert _ink_between(np.array(blank + ink), 0, 30)
    # 框条下沿渐淡的墨紧贴着满宽段、没有白：不是字（殿本 vol20 p179 双线框）
    tail = list(np.linspace(0.8, 0.05, 25)) + [0.1] * 5
    assert not _ink_between(np.array(tail), 0, 30)
    # 先白、墨太短（里层细线）
    assert not _ink_between(np.array(blank + [0.9] * 3 + [0.0] * 22), 0, 30)


def test_weak_top_floor_skips_near_lines():
    """写本档（floor 给值）：先按挪动量筛（字顶附近的碎横不算），再取投影 ≥ floor 的最靠页心的一条（框条下的细虚线）。"""
    m = np.zeros((2684, 1000))
    m[40:60, :] = 1.0                      # 粗框条
    m[92:94, ::3] = 1.0                    # 框条下细虚线（约 0.33）
    m[140:142, ::4] = 1.0                  # 字顶附近碎横（约 0.25），离选中线不到 0.021 页高
    m[152:154, ::2] = 1.0                  # 首行字顶（选中线，约 0.5：门槛给 0.6 时算弱）
    r = _weak_top_guard(m, _match(152.0), 0, 400, 0.6, 1.0, 2, floor=0.25)
    assert 90 <= r.position <= 95
    r0 = _weak_top_guard(m, _match(152.0), 0, 400, 0.3, 1.0, 2)   # 殿本档：选中线够强，不动
    assert r0.position == 152.0


def test_weak_top_wild_slope_measured_on_page_level():
    """选中线倾角搜飞（vol93 p18 约 1.1°）：在它自己的倾角上量，真框被斜着摊薄、护栏不触发；
    改在带里横墨最强那一档倾角上量，就能挪回真框。"""
    m = np.zeros((1920, 1000))
    m[60:66, :] = 1.0
    xs = np.arange(0, 1000, 2)
    ys = np.round(300 + 0.02 * (xs - 500)).astype(int)
    m[ys, xs] = 1.0
    m[ys + 1, xs] = 1.0
    r = _weak_top_guard(m, LineMatch(position=300.0, slope=0.02, score=1.0, width=2.0, proj=1.0),
                        0, 288 + 60, TOP_WEAK_RATIO, 1.0, 2)
    assert 56 <= r.position <= 70 and abs(r.slope) < 0.01


# ── 下版框弱线护栏（镜像，2026-11-08）──────────────────────────
from open_guji_cv.seg.lines import _weak_bottom_guard  # noqa: E402


def _bottom_page(weak_y: int = 1770) -> np.ndarray:
    """1920×1000 页：y 1850–1861 粗框条满宽，weak_y 一条只占两成宽的细横墨（末行字底）。"""
    m = np.zeros((1920, 1000))
    m[1850:1862, :] = 1.0
    m[weak_y:weak_y + 2, ::5] = 1.0
    return m


def test_weak_bottom_moves_down_to_strong_bar():
    r = _weak_bottom_guard(_bottom_page(), _match(1770.0), 1632, 1919, TOP_WEAK_RATIO, 1.0, 2)
    assert 1848 <= r.position <= 1864


def test_weak_bottom_keeps_strong_line():
    r = _weak_bottom_guard(_bottom_page(), _match(1855.0), 1632, 1919, TOP_WEAK_RATIO, 1.0, 2)
    assert r.position == 1855.0


def test_weak_bottom_never_moves_up():
    """强线在选中线上方（选中的是外框下的碎墨）不往上挪：往上会切字。"""
    m = np.zeros((1920, 1000))
    m[1700:1712, :] = 1.0
    m[1850:1852, ::5] = 1.0
    r = _weak_bottom_guard(m, _match(1850.0), 1632, 1919, TOP_WEAK_RATIO, 1.0, 2)
    assert r.position == 1850.0


def test_find_horizontal_border_bottom_guard_off_by_default():
    from open_guji_cv.seg.lines import find_horizontal_border
    m = _bottom_page()
    assert find_horizontal_border(m, "bottom").position == find_horizontal_border(m, "bottom", weak_bottom_ratio=0.0).position
