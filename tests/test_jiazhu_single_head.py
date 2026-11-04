"""jiazhu_split.single_row_heads：一行就完的雙行小注段头（全唐文「字｜闕」＋「一」，2026-11-04）。"""
import numpy as np

from open_guji_cv.books.siku_zongmu import jiazhu_split as J


def _patch(right: bool, left: bool, w: int = 40, h: int = 40) -> np.ndarray:
    p = np.full((h, w), 255, np.uint8)
    if right:
        p[5:35, 24:36] = 0
    if left:
        p[5:35, 4:16] = 0
    return p


def test_head_row_followed_by_right_half_tail_is_adopted():
    entries = [(1, (20.0, 900.0)), (2, None), (3, None)]
    patches = {1: _patch(True, True), 2: _patch(True, False), 3: _patch(True, True)}
    assert J.single_row_heads(entries, {}, patches, eligible={1, 2, 3}) == {1: 20.0}


def test_next_row_full_width_is_not_adopted():
    entries = [(1, (20.0, 900.0)), (2, None)]
    patches = {1: _patch(True, True), 2: _patch(True, True)}
    assert J.single_row_heads(entries, {}, patches, eligible={1, 2}) == {}


def test_weak_gap_and_existing_runs_are_skipped():
    patches = {1: _patch(True, True), 2: _patch(True, False)}
    assert J.single_row_heads([(1, (20.0, J.CC_MIN - 1)), (2, None)], {}, patches) == {}
    assert J.single_row_heads([(1, (20.0, 900.0)), (2, None)], {2: 20.0}, patches) == {}
