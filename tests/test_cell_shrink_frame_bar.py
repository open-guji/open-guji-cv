# -*- coding: utf-8 -*-
"""抬头位里的版框线不当字（cell_shrink._is_raised_frame_bar，2026-09-25）。"""
from types import SimpleNamespace

from open_guji_cv.steps.cell_shrink import _is_raised_frame_bar

CC = SimpleNamespace(period=113.0, content_x=(5.0, 185.0),
                     cells=[SimpleNamespace(slot=1, sub=None, y0=10.0, y1=123.0)])


def test_flat_full_width_box_in_raised_slot_is_a_frame_bar():
    assert _is_raised_frame_bar(-1, "char", (20, 12, 175, 25), CC)       # vol02 p123c9：高 13、宽 155


def test_real_raised_char_and_body_slots_are_kept():
    assert not _is_raised_frame_bar(-1, "char", (40, 10, 150, 125), CC)  # 抬头「御」高 115
    assert not _is_raised_frame_bar(3, "char", (20, 500, 175, 513), CC)  # 正文里的「一」不管
    assert not _is_raised_frame_bar(1, "char", (20, 60, 175, 72), CC)    # 首格居中的「一」不管
    assert not _is_raised_frame_bar(-1, "char", (80, 12, 110, 25), CC)   # 窄的小墨点不是框线
    assert not _is_raised_frame_bar(-1, "empty", (20, 12, 175, 25), CC)


def test_top_frame_line_in_first_slot():
    assert _is_raised_frame_bar(1, "char", (20, 14, 175, 28), CC)       # vol02 p58c4：贴格顶的上边框线
