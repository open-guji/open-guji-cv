"""Step2 列窗上界按版框修正（2026-09-20）：`refine_top_by_frame`。

bxgb p48/p54：Step1 的上版框直线落在首行字的顶边而不是框上（低 12~22px）。首字比上界高的
顶部整块不在列图里；首字顶边恰在上界的，被 `column_border_trim` 当贴边薄线削掉 6~16 行
（二 变一、三 变二、六 丢点、冢 丢宀）。合成一页：满宽框条 + 框下的字墨，top_y 故意给低，
期望上界提到框下沿；框贴着上界（正常）的不动；二/三 的宽横不是框。
"""

from __future__ import annotations

import numpy as np

from open_guji_cv.utils.border_geometry import VLine
from open_guji_cv.utils.column_projection import ColumnWindow, refine_top_by_frame

W, H = 300, 400
RAW_L, RAW_R = 50, 150            # 列在原图里的 x 范围


def _win(top_y: float, raised: bool = False) -> ColumnWindow:
    # 新坐标 x = (W-1) - raw_x；left 是页面左侧那条线（raw x 小 → 新坐标 x 大）
    left = VLine(x_at_top=float((W - 1) - RAW_L), slope=0.0)
    right = VLine(x_at_top=float((W - 1) - RAW_R), slope=0.0)
    return ColumnWindow(col=1, left=left, right=right, top_y=top_y, bottom_y=380.0,
                        border_top_y=top_y, border_bottom_y=370.0, raised=raised)


def _page(frame_rows=(100, 112), text_rows=(118, 150)) -> np.ndarray:
    g = np.full((H, W), 255, np.uint8)
    g[frame_rows[0]:frame_rows[1], :] = 0                       # 满宽版框
    g[text_rows[0]:text_rows[1], RAW_L + 25:RAW_R - 25] = 0     # 框下的字（宽 0.5，不满宽）
    g[200:380, RAW_L + 20:RAW_R - 20] = 0                        # 下面的正文
    return g


def test_top_moves_up_to_frame_bottom():
    win = _win(130.0)                       # 落在字墨中间
    d = refine_top_by_frame(_page(), win)
    assert d > 0
    assert abs(win.top_y - 112) <= 2, win.top_y
    assert win.border_top_in_column == 0.0


def test_frame_adjacent_to_top_is_left_alone():
    win = _win(113.0)                       # 框下沿就在上界上方 1 行：正常贴框
    assert refine_top_by_frame(_page(), win) == 0.0
    assert win.top_y == 113.0


def test_moves_even_when_only_white_lies_between():
    """首字顶边恰在上界的情形（二 变一）：框与上界之间只有白，也要提——列图该从框内缘起。"""
    win = _win(118.0)                       # 框下沿 112，中间 6 行白，字从 118 起
    d = refine_top_by_frame(_page(), win)
    assert d > 0 and abs(win.top_y - 112) <= 2


def test_wide_stroke_is_not_a_frame():
    """二/三 的顶横：宽但不满宽（0.7）——不能被当成框把上界提上去。"""
    g = np.full((H, W), 255, np.uint8)
    g[100:106, RAW_L + 15:RAW_R - 15] = 0   # 0.7 宽的横
    g[118:150, RAW_L + 25:RAW_R - 25] = 0
    win = _win(130.0)
    assert refine_top_by_frame(g, win) == 0.0


def test_raised_or_framed_columns_untouched():
    g = _page()
    w1 = _win(130.0, raised=True)
    assert refine_top_by_frame(g, w1) == 0.0
    w2 = _win(130.0)
    w2.border_top_y = 140.0                 # border_top_in_column > 0：框在列图里，另一套逻辑
    assert refine_top_by_frame(g, w2) == 0.0
