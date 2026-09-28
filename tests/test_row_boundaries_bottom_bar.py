# -*- coding: utf-8 -*-
"""列里残留的下版框线（`row_boundaries.find_bottom_frame_bar`，overview#266）。

合成列图按 vol03 实测几何画：列宽 180、字距 115、字身 ~0.6 列宽；框线满宽、
厚 5~20 行；`border_bottom` 落在框下白纸上（高出 45~77 行那一类）或落在外框上
（双边框，内框在其上 20~30 行那一类）。"""

from __future__ import annotations

import numpy as np

from open_guji_cv.utils import row_boundaries as RB

W, H, P = 180, 2560, 115.0
BB = 2536.0                      # border_bottom（列图坐标，框下白纸）


def _column(n_chars: int = 21) -> np.ndarray:
    """白底列图，前 n_chars 格各画一个「十」形字（横 0.6 列宽、竖在中间）。"""
    img = np.full((H, W), 255, np.uint8)
    for k in range(n_chars):
        y0 = int(10 + k * P)
        img[y0 + 50:y0 + 58, 36:144] = 0          # 横
        img[y0 + 15:y0 + 100, 86:94] = 0          # 竖
    return img


def _bar(img: np.ndarray, y: int, h: int, x0: int = 0, x1: int = W) -> None:
    img[y:y + h, x0:x1] = 0


def test_bar_above_border_bottom_is_found():
    img = _column(20)            # 20 字占到 ~2295，框在 2470
    _bar(img, 2470, 8)
    assert RB.find_bottom_frame_bar(img, 0, W, BB, P) == 2470.0


def test_no_frame_keeps_last_char_horizontal():
    # 末字是「一」：0.75 列宽、10 行厚，其下到 border_bottom 全白——不是框（不够满宽）
    img = _column(20)
    _bar(img, 2400, 10, x0=22, x1=157)
    assert RB.find_bottom_frame_bar(img, 0, W, BB, P) is None


def test_double_frame_returns_inner_line():
    # 外框粗且满宽，内框细、断续（峰值 ~0.65）、两头贴墙，在外框上方 22 行
    img = _column(20)
    _bar(img, 2500, 14)                           # 外框
    for x in range(0, W, 12):                     # 内框：每 12px 断 4px
        _bar(img, 2474, 4, x0=x, x1=min(W, x + 8))
    assert RB.find_bottom_frame_bar(img, 0, W, BB, P) == 2474.0


def test_char_below_bar_means_not_a_frame():
    img = _column(20)
    _bar(img, 2420, 8)
    img[2460:2500, 80:100] = 0                    # 线下还有字墨
    assert RB.find_bottom_frame_bar(img, 0, W, BB, P) is None


def test_segment_column_ends_last_cell_at_bar():
    img = _column(21)            # 21 字到 ~2410，框在 2440（高出 border_bottom 96 行）
    _bar(img, 2440, 10)
    on = RB.segment_column(img, P, n_body_slots=21, border_top=0.0, border_bottom=BB, ref_w=W)
    off = RB.segment_column(img, P, n_body_slots=21, border_top=0.0, border_bottom=BB, ref_w=W,
                            detect_bottom_bar=False)
    assert on.bottom_bar_y == 2440.0
    assert on.cells[-1].y1 == 2440.0              # 末格到框线上沿为止，不含框
    assert on.cells[-1].kind == "char"
    assert off.bottom_bar_y is None
    assert off.cells[-1].y1 > 2445                # 不开时末格把框线包进去（旧行为）


def test_bar_already_at_border_bottom_does_not_move_it():
    img = _column(20)
    _bar(img, int(BB) - 10, 8)                    # 框就在 border_bottom 的余量里
    r = RB.segment_column(img, P, n_body_slots=21, border_top=0.0, border_bottom=BB, ref_w=W)
    assert r.bottom_bar_y is None


def test_bar_that_would_squeeze_the_column_falls_back():
    # 框线占着末格的位置（tests/fixtures 真页 c3 的形态）：收下界后 22 格装不进框线以内，
    # DP 会在列中间硬挤出一格（本例第 8~13 条格线整体上移 ~120 行）——这种列退回原下界的解
    img = _column(21)                               # 21 字到 ~2410
    _bar(img, 2440, 10)
    kw = dict(n_body_slots=22, border_top=0.0, border_bottom=BB, ref_w=W)
    proj = RB.row_ink_projection(img, 0, W, 128)
    squeezed = RB.fit_row_boundaries(proj, W, 0.0, 2440.0, P, n_slots=22)
    off = RB.segment_column(img, P, detect_bottom_bar=False, **kw)
    assert abs(squeezed.boundaries[10] - off.boundaries[10]) > 60     # 前提：直接收下界确实会挤
    on = RB.segment_column(img, P, **kw)
    assert [round(b) for b in on.boundaries] == [round(b) for b in off.boundaries]
