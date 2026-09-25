# -*- coding: utf-8 -*-
"""只有框线的格判空（row_boundaries._frame_mask/_frame_only，2026-09-26）。"""
import numpy as np

from open_guji_cv.utils import row_boundaries as RB

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
