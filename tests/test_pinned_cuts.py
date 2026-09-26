# -*- coding: utf-8 -*-
"""人拖过的切线钉住（segment_column pinned_cuts，2026-09-26）。"""
import numpy as np

from open_guji_cv.utils import row_boundaries as RB

SLOT_H, N = 60, 6


def _column():
    img = np.full((SLOT_H * N + 20, 80), 255, np.uint8)
    for k in range(N):                       # 每格一个方块字，格间留白
        y0 = 10 + k * SLOT_H + 12
        img[y0:y0 + 36, 20:60] = 0
    return img


def _bounds(**kw):
    r = RB.segment_column(_column(), period=SLOT_H, n_body_slots=N, border_top=10.0,
                          border_bottom=10.0 + SLOT_H * N, **kw)
    return [round(b) for b in r.boundaries]


def test_pin_moves_only_that_boundary():
    base = _bounds()
    y = base[3] - 5
    pinned = _bounds(pinned_cuts={3: y})
    assert pinned[3] == round(y)
    assert [b for i, b in enumerate(pinned) if i != 3] == [b for i, b in enumerate(base) if i != 3]


def test_pin_matches_by_position_when_slot_numbers_shifted():
    """格号错了一位（上游几何变了），钉子按位置认最近那条格线。"""
    base = _bounds()
    pinned = _bounds(pinned_cuts={3: base[4] - 3})            # 格号说 3，位置贴着第 4 条
    assert pinned[4] == base[4] - 3 and pinned[3] == base[3]


def test_pin_far_from_everything_is_ignored():
    base = _bounds()
    assert _bounds(pinned_cuts={99: 5.0}) == base              # 格号不存在、位置也不挨着
    assert _bounds(pinned_cuts={3: base[3] + 2 * SLOT_H}) == base   # 离得太远（>1.5 格）
