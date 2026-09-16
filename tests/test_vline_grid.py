"""网格模式竖线探测（`find_vertical_lines_grid`）：列数已知、缺槽插值、页边假线排除。

合成页模仿北行日錄刻本的病：19 列（20 条线）里抠掉 3 条界行，其中两个空槽里
再画一块 60px 宽的"字身"假峰，版框外再加一条页边假线。
"""
import numpy as np

from open_guji_cv.utils.border_geometry import detect_borders
from open_guji_cv.utils.peak_line_search import (
    find_vertical_lines,
    find_vertical_lines_grid,
)

H, W = 600, 2400
N_COLS = 19
PITCH = 115
X0 = 100
XS_ALL = [X0 + k * PITCH for k in range(N_COLS + 1)]        # 100 .. 2285
MISSING = {5, 11, 12}                                       # 没印出来的界行槽位
PAGE_EDGE = 2390                                            # 版框外的页边假线


def _page(missing=MISSING, humps=(5, 11), page_edge=True) -> np.ndarray:
    mask = np.zeros((H, W), dtype=np.float64)
    for k, x in enumerate(XS_ALL):
        if k in missing:
            continue
        y0, y1 = (0, H) if k in (0, N_COLS) else (50, H - 50)   # 版框通页，界行只在框内
        mask[y0:y1, x - 1:x + 2] = 1.0
    for k in humps:                                          # 空槽里的"字身"：宽、实
        x = XS_ALL[k]
        mask[60:H - 60, x - 30:x + 30] = 1.0
    if page_edge:
        mask[:, PAGE_EDGE - 1:PAGE_EDGE + 2] = 1.0
    mask[40:44, :] = 1.0                                     # 上下版框
    mask[H - 44:H - 40, :] = 1.0
    return mask


def test_grid_returns_exact_count_and_fills_missing_slots():
    lines, filled = find_vertical_lines_grid(_page(), n_lines=N_COLS + 1)
    assert len(lines) == N_COLS + 1
    assert [i for i, f in enumerate(filled) if f] == sorted(MISSING)
    for k, (ln, x) in enumerate(zip(lines, XS_ALL)):
        assert abs(ln.position - x) <= 2, (k, ln.position, x)
    # 插值槽的分数记 0，探到的槽分数为正
    assert all(lines[k].score == 0.0 for k in MISSING)
    assert all(lines[k].score > 0.0 for k in range(N_COLS + 1) if k not in MISSING)


def test_grid_excludes_page_edge_even_though_it_is_the_strongest_line():
    """页边那条线通页、比界行还实，自由模式会把它当成一条线；网格模式按列距把它排掉。"""
    free = find_vertical_lines(_page(), expected_count=N_COLS + 1)
    assert any(abs(r.position - PAGE_EDGE) <= 3 for r in free)
    lines, _ = find_vertical_lines_grid(_page(), n_lines=N_COLS + 1)
    assert all(abs(ln.position - PAGE_EDGE) > 50 for ln in lines)
    assert abs(lines[-1].position - XS_ALL[-1]) <= 2


def test_grid_does_not_take_a_text_hump_for_a_missing_rule():
    """空槽里那块 60px 宽的"字身"半高宽 ~60、分数 ~H/60=10：两条闸都得拦住它。"""
    lines, filled = find_vertical_lines_grid(_page(), n_lines=N_COLS + 1)
    for k in (5, 11):
        assert filled[k]
        assert lines[k].width == 0.0
        assert abs(lines[k].position - XS_ALL[k]) <= 2


def test_grid_with_col_pitch_prior_gives_same_answer():
    a, fa = find_vertical_lines_grid(_page(), n_lines=N_COLS + 1)
    b, fb = find_vertical_lines_grid(_page(), n_lines=N_COLS + 1, col_pitch=PITCH)
    assert fa == fb
    assert [round(x.position, 3) for x in a] == [round(x.position, 3) for x in b]


def test_grid_with_all_rules_printed_marks_nothing_filled():
    lines, filled = find_vertical_lines_grid(_page(missing=set(), humps=()), n_lines=N_COLS + 1)
    assert not any(filled)
    assert len(lines) == N_COLS + 1


def test_detect_borders_grid_mode_threads_filled_flags_through_flip():
    """经 detect_borders：新坐标 x 向左递增，verticals 顺序反过来，filled 要跟着翻。"""
    gray = np.where(_page() > 0, 0.0, 255.0)
    res = detect_borders(gray, expected_cols=N_COLS, column_grid=True, col_pitch=PITCH)
    assert len(res.verticals) == N_COLS + 1
    assert len(res.vline_filled) == N_COLS + 1
    # 旧坐标槽位 k → 新坐标下标 N_COLS − k
    assert [i for i, f in enumerate(res.vline_filled) if f] == sorted(N_COLS - k for k in MISSING)
    xs_new = [v.x_at_top for v in res.verticals]
    assert xs_new == sorted(xs_new)


def test_detect_borders_free_mode_reports_no_filled():
    gray = np.where(_page(missing=set(), humps=()) > 0, 0.0, 255.0)
    res = detect_borders(gray, expected_cols=N_COLS)
    assert res.vline_filled == [False] * len(res.verticals)
