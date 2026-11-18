# -*- coding: utf-8 -*-
"""只有框线的格判空（row_boundaries._frame_mask/_frame_only，2026-09-26）。"""
import numpy as np

from open_guji_cv.impl.keben import row_boundaries as RB

P = 60.0


def _col(h=300, w=100):
    return np.zeros((h, w), np.uint8)


def test_edge_vertical_spanning_cells_is_frame():
    ink = _col()
    ink[0:200, 85:92] = 1                       # 贴右边、跨三格多的竖（装饰框/版框的边）
    fr = RB._frame_mask(ink, P)
    assert fr.any()
    cell = slice(60, 120)
    assert RB._frame_only(ink[cell], fr[cell], P, 0.01)


def test_centered_long_vertical_is_not_frame():
    """「十」的竖与下一字起笔连成一线也不算框（bxgb A/B 教训）。"""
    ink = _col()
    ink[0:200, 47:54] = 1
    ink[30:36, 20:80] = 1
    assert not RB._frame_mask(ink, P).any()


def test_real_char_next_to_frame_is_kept():
    ink = _col()
    ink[0:200, 85:92] = 1
    ink[70:110, 20:60] = 1                      # 框边旁边一个实心字
    fr = RB._frame_mask(ink, P)
    cell = slice(60, 120)
    assert not RB._frame_only(ink[cell], fr[cell], P, 0.01)


def test_closed_box_glyph_not_frame():
    """「曰」类闭口方框字：两侧竖+多道横档，不得当框角判空（vol14 32 葉 7 列）。"""
    ink = _col(h=300, w=190)
    ink[0:300, 62:66] = 1                       # 他格也有的左侧长竖（模拟被收进 frame 的两侧竖）
    ink[0:300, 124:130] = 1
    for y in (78, 108, 144):
        ink[y:y + 5, 62:130] = 1
    fr = RB._frame_mask(ink, P)
    cell = slice(60, 171)
    assert fr[cell].any()
    assert not RB._frame_only(ink[cell], fr[cell], P, 0.01)


def test_numeral_two_beside_frame_not_frame():
    """「二」「三」：窗口比字宽得多（末列）、横画端点落进框线邻域时，不得整格判空（殿本 vol68 230:9、vol63 116:9）。"""
    ink = _col(h=300, w=220)
    ink[0:300, 8:14] = 1                         # 版框竖线，穿过几格
    for y in (82, 112):
        ink[y:y + 9, 14:48] = 1                  # 两道横画，宽 34 ≈ 0.57 period，左端紧贴框线
    fr = RB._frame_mask(ink, P)
    cell = slice(60, 171)
    assert fr[cell].any()
    assert not RB._frame_only(ink[cell], fr[cell], P, 0.01)
    # 对照：只有一道边的框角照旧判空
    corner = _col(h=300, w=220)
    corner[0:300, 8:14] = 1
    corner[100:108, 14:200] = 1
    fc = RB._frame_mask(corner, P)
    assert RB._frame_only(corner[cell], fc[cell], P, 0.01)
