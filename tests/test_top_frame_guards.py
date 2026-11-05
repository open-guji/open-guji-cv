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
