"""row_boundaries._half_a_left：只有右半有字的夹注格，跨缝的字整字发右半（jiazhu_half_a，全唐文 S3，2026-11-05）。"""
import numpy as np

from open_guji_cv.books.quantangwen import jiazhu_split as J
from open_guji_cv.books.quantangwen import row_boundaries as RB


def _blank(w: int = 60, h: int = 60) -> np.ndarray:
    return np.full((h, w), 255, np.uint8)


def test_stroke_crossing_seam_extends_left_edge():
    p = _blank()
    p[20:26, 10:55] = 0          # 居中的「一」横跨缝（缝在 30）
    assert RB._half_a_left(p, 30, 128) == 10


def test_separate_left_component_is_not_taken():
    p = _blank()
    p[10:50, 34:50] = 0          # 右半的字
    p[10:50, 4:14] = 0           # 左半另一块（邻行残墨），不压右半
    assert RB._half_a_left(p, 30, 128) == 30


def test_speck_touching_right_half_is_ignored():
    p = _blank()
    p[10:50, 34:50] = 0
    p[30:33, 5:31] = 0           # 细长一条压着缝，但面积够 → 算；改成面积小的点
    p2 = _blank()
    p2[10:50, 34:50] = 0
    p2[30:33, 28:31] = 0         # 3x3 噪点压着缝，面积 < HALF_A_MIN_AREA
    assert RB._half_a_left(p, 30, 128) == 5
    assert RB._half_a_left(p2, 30, 128) == 30


def test_no_ink_on_right_returns_none():
    p = _blank()
    p[10:50, 4:20] = 0           # 字整个偏在左半
    assert RB._half_a_left(p, 30, 128) is None
    assert J.HALF_MIN_INK > 0
