"""detect_intrusion 单测：合成的界行/版框 vs 真笔画。

判据的全部价值在于**分得开**——「三」的横笔、「中」的竖笔与版面线在
「细 + 贯穿」上完全一样，靠的是贴不贴外带。故正反例都要造。
"""

import numpy as np
import pytest

from open_guji_cv.clustering.crop_quality import detect_intrusion

S = 64


def _blank() -> np.ndarray:
    return np.full((S, S), 255, np.uint8)


def _body(img: np.ndarray) -> np.ndarray:
    """在核心区画个「字身」，免得图块只剩一条线（那是 not_text 不是混入）。"""
    img[18:46, 18:46] = 0
    img[24:40, 24:40] = 255
    return img


def test_vertical_rule_bar_left_and_right():
    left = _body(_blank())
    left[:, 3:6] = 0                      # 贴左边的全高细竖线
    assert "rule_bar_left" in detect_intrusion(left)

    right = _body(_blank())
    right[:, S - 6:S - 3] = 0
    assert "rule_bar_right" in detect_intrusion(right)


def test_horizontal_frame_bar_top_and_bottom():
    top = _body(_blank())
    top[2:5, :] = 0
    assert "frame_bar_top" in detect_intrusion(top)

    bot = _body(_blank())
    bot[S - 5:S - 2, :] = 0
    assert "frame_bar_bottom" in detect_intrusion(bot)


def test_central_stroke_is_not_a_rule_bar():
    """「中」的竖笔贯穿全高，但在图块正中——不是界行。"""
    img = _body(_blank())
    img[:, S // 2 - 1:S // 2 + 2] = 0
    assert not [c for c in detect_intrusion(img) if c.startswith("rule_bar")]


def test_thick_bar_is_a_stroke_not_a_line():
    """厚到一定程度就是笔画（或整块脏）——版面线是线。"""
    img = _body(_blank())
    img[:, 2:2 + int(S * 0.4)] = 0
    assert not [c for c in detect_intrusion(img) if c.startswith("rule_bar")]


def test_clean_body_and_blank_are_silent():
    assert detect_intrusion(_body(_blank())) == []
    assert detect_intrusion(_blank()) == []


def test_tiny_and_color_inputs_are_safe():
    assert detect_intrusion(np.full((4, 4), 255, np.uint8)) == []
    color = np.dstack([_body(_blank())] * 3)
    assert detect_intrusion(color) == []


def test_multiple_codes_reported_together():
    img = _body(_blank())
    img[:, 3:6] = 0
    img[S - 5:S - 2, :] = 0
    codes = detect_intrusion(img)
    assert "rule_bar_left" in codes and "frame_bar_bottom" in codes


@pytest.mark.parametrize("fill", [0.3, 0.95])
def test_fill_threshold_is_a_knob(fill):
    """填充阈可调（评测扫参用），但默认值不动——标定见 docstring。"""
    img = _body(_blank())
    img[:, 3:6] = 0
    img[10:50, 3:6] = 255          # 打断竖线：只剩两小段
    codes = detect_intrusion(img, v_fill=fill)
    assert ("rule_bar_left" in codes) == (fill <= 0.4)
