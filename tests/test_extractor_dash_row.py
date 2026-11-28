"""列端虚线行（cell_shrink.end_dash_row → extractor.strip_dash_row，CV2 2026-11-27）。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.clustering.extractor import strip_dash_row

CELL_H = 120.0


def _char(h: int = 150, w: int = 160) -> np.ndarray:
    """字身：一个粗竖＋一横，竖往下伸到 y=140（像越过虚线的勾）。"""
    p = np.full((h, w), 255, np.uint8)
    p[10:140, 70:80] = 0
    p[40:48, 20:140] = 0
    return p


def _dashes(p: np.ndarray, y: int = 128, xs=((95, 112), (118, 124), (130, 148), (5, 20), (30, 40))) -> np.ndarray:
    for a, b in xs:
        p[y:y + 4, a:b] = 0
    return p


def test_dash_row_removed_hook_kept():
    p = _dashes(_char())
    out = strip_dash_row(p, 0.0, 135.0, CELL_H, bottom=True)
    assert (out[128:132, 95:112] == 255).all() and (out[128:132, 5:20] == 255).all()
    assert (out[10:140, 70:80] == 0).all()          # 字身（含越线的勾）不动


def test_lone_flat_stroke_kept():
    """字底下单独一横（不成排）不抹。"""
    q = _char(); q[128:132, 95:140] = 0      # 一段扁块、离字身远
    assert (strip_dash_row(q, 0.0, 135.0, CELL_H) == q).all()


def test_dots_not_flat_kept():
    """灬 一类：一排点，高过 DASH_ROW_MAX_H（0.07 格高）不认。"""
    p = _char()
    for a in (20, 50, 95, 125):
        p[115:135, a:a + 12] = 0
    assert (strip_dash_row(p, 0.0, 135.0, CELL_H) == p).all()


def test_row_above_char_middle_not_removed_at_tail():
    """列尾格：排在字身上半（不是框线那一侧）的不认。"""
    p = _char()
    _dashes(p, y=20)
    assert (strip_dash_row(p, 0.0, 135.0, CELL_H, bottom=True) == p).all()


def test_head_row_removed():
    p = np.full((150, 160), 255, np.uint8)
    p[30:140, 70:80] = 0
    _dashes(p, y=8)
    out = strip_dash_row(p, 15.0, 150.0, CELL_H, bottom=False)
    assert (out[8:12, 95:112] == 255).all()
