"""seg.seam.fit_row_cuts：一行字自己的横格线（写本雙行小注两行各切，2026-11-03）。"""
import numpy as np

from open_guji_cv.seg.seam import fit_row_cuts


def _row(chars: list[tuple[int, int]], length: int) -> np.ndarray:
    r = np.zeros(length)
    for a, b in chars:
        r[a:b] = 0.4
    return r


def test_cuts_follow_row_gaps_not_shared_grid():
    # 段 0–400 四格，共用格线 0/100/200/300/400；这一行的字错开了半格：字在 50–140、150–240、250–340、350–395
    ink = _row([(10, 40), (50, 140), (150, 240), (250, 340), (350, 395)], 400)
    ink[:45] = 0.0          # 段首上半格空
    cuts = fit_row_cuts(ink, 0, 400, 4, anchor=[0, 100, 200, 300, 400])
    assert cuts[0] == 0 and cuts[-1] == 400
    for y in cuts[1:-1]:
        assert ink[int(y)] == 0.0             # 每条切线都落在字缝里


def test_keeps_shared_grid_when_it_is_clean():
    ink = _row([(10, 90), (110, 190), (210, 290), (310, 390)], 400)
    cuts = fit_row_cuts(ink, 0, 400, 4, anchor=[0, 100, 200, 300, 400])
    assert cuts == [0.0, 100.0, 200.0, 300.0, 400.0]


def test_degenerate():
    ink = np.zeros(10)
    assert fit_row_cuts(ink, 0, 10, 1) == [0.0, 10.0]
    assert fit_row_cuts(ink, 0, 3, 4) is None
