"""seg.frame_line：整页拟双边版框的内框细线（自造图）。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.seg.frame_line import fit_inner_frame_line


def _page(side: str = "bottom", tilt: float = 0.004, dashed: bool = True, chars: bool = True):
    """造一张 1200 宽的页：外粗框 8 行、离它 12 行一道 3 行厚的内虚线，字脚压在内线上。"""
    h, w = 600, 1200
    ink = np.zeros((h, w), bool)
    rng = np.random.default_rng(1)
    for x in range(50, 1150):
        o = 500 + tilt * (x - 600) if side == "bottom" else 100 + tilt * (x - 600)
        o = int(round(o))
        if side == "bottom":
            ink[o:o + 8, x] = True                       # 外框朝页心一边在 o
            c = o - 12 - 2                                # 内线 3 行：[c, c+3)
        else:
            ink[o - 8:o, x] = True
            c = o + 12 - 1
        if not dashed or (x // 20) % 3 != 2:              # 每 60px 断 20px
            ink[c:c + 3, x] = True
    if chars:   # 字：竖笔一直压到内线上、横笔离线一段
        for cx in range(80, 1150, 110):
            ys = (380, 487) if side == "bottom" else (113, 220)
            ink[ys[0]:ys[1], cx:cx + 6] = True
            ink[ys[0] + 40:ys[0] + 46, cx - 30:cx + 36] = True
    ink |= rng.random((h, w)) < 0.002
    return ink


def test_bottom_inner_line_found_through_dashes_and_touching_strokes():
    ink = _page("bottom")
    line = fit_inner_frame_line(ink, 50, 1150, y_hint=500, cell_h=80, side="bottom")
    assert line is not None
    for x in (100, 600, 1100):
        o = 500 + 0.004 * (x - 600)
        assert abs(float(line.y(x)) - (round(o) - 12.5)) <= 1.0
    assert 2 <= line.thick <= 4
    assert float(line.text_edge(600)) < float(line.y(600))


def test_top_inner_line():
    ink = _page("top")
    line = fit_inner_frame_line(ink, 50, 1150, y_hint=100, cell_h=80, side="top")
    assert line is not None
    assert abs(float(line.y(600)) - 112.5) <= 1.0
    assert float(line.text_edge(600)) > float(line.y(600))


def test_no_frame_returns_none():
    ink = _page("bottom")
    ink[440:, :] = False            # 没有版框
    assert fit_inner_frame_line(ink, 50, 1150, y_hint=500, cell_h=80, side="bottom") is None
