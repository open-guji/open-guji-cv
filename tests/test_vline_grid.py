"""网格模式竖线探测（`find_vertical_lines_grid`）：列数已知、缺槽插值、页边假线排除。

合成页模仿北行日錄刻本的病：19 列（20 条线）里抠掉 3 条界行，其中两个空槽里
再画一块 60px 宽的"字身"假峰，版框外再加一条页边假线。
"""
import numpy as np
import pytest

from open_guji_cv.utils.border_geometry import detect_borders
from open_guji_cv.utils.peak_line_search import (
    LineMatch,
    find_vertical_lines,
    find_vertical_lines_grid,
    interpolate_missing,
    is_thin_rule,
    select_frame_pair,
    verify_slots,
    _vline_pool,
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


# ── 三步各自的单元测（拆函数之后才测得动） ──────────────────────────────

def _lm(pos, score=100.0, width=4.0, proj=500.0, slope=0.0) -> LineMatch:
    return LineMatch(position=pos, slope=slope, score=score, width=width, proj=proj)


def test_is_thin_rule_is_the_single_yardstick():
    """选版框对和逐槽验线共用同一把尺子——两处判据不一致会出现
    「支持数算它、验线不认它」的错位。"""
    assert is_thin_rule(_lm(100, score=100.0, width=4.0))
    assert not is_thin_rule(_lm(100, score=10.0, width=4.0))     # 分数不够（字身假峰）
    assert not is_thin_rule(_lm(100, score=100.0, width=60.0))   # 太宽（字身假峰）
    assert not is_thin_rule(_lm(100, score=100.0, width=0.0))    # 插值线（width=0）


def test_select_frame_pair_picks_the_span_that_lines_up_with_thin_rules():
    pool, _ = _vline_pool(_page(), 60, 90, 200, 0.5, 3)
    a, b = select_frame_pair(pool, N_COLS + 1)
    assert abs(a.position - XS_ALL[0]) <= 2
    assert abs(b.position - XS_ALL[-1]) <= 2
    # 页边假线在池里，但不该被选成版框
    assert all(abs(x.position - PAGE_EDGE) > 50 for x in (a, b))


def test_select_frame_pair_returns_none_when_col_pitch_excludes_everything():
    """列距先验大到整页装不下 → 选不出对，`find_vertical_lines_grid` 据此退回自由模式的截断。

    ⚠️ 别拿**过小**的 col_pitch 当反例：候选池里总找得出两条只隔 10px 的线
    （实测 pitch=10 时 1521→1710 这一对就满足），过小反而选得出。真正选不出的
    是过大——整页宽度除以槽数封顶。"""
    pool, _ = _vline_pool(_page(), 60, 90, 200, 0.5, 3)
    assert select_frame_pair(pool, N_COLS + 1, col_pitch=float(W)) is None


def test_verify_slots_leaves_none_where_no_rule_was_printed():
    mask = _page()
    pool, bank = _vline_pool(mask, 60, 90, 200, 0.5, 3)
    a, b = select_frame_pair(pool, N_COLS + 1)
    lines = verify_slots(mask, a, b, N_COLS + 1, bank)
    assert len(lines) == N_COLS + 1
    assert [i for i, ln in enumerate(lines) if ln is None] == sorted(MISSING)
    assert lines[0] is a and lines[-1] is b        # 两端原样透传


def test_interpolate_missing_fills_linearly_and_marks_filled():
    lines = [_lm(0.0, slope=0.0), None, None, _lm(300.0, slope=0.03)]
    out, filled = interpolate_missing(lines)
    assert filled == [False, True, True, False]
    assert [round(x.position, 6) for x in out] == [0.0, 100.0, 200.0, 300.0]
    assert [round(x.slope, 6) for x in out] == [0.0, 0.01, 0.02, 0.03]
    # 插出来的线标记成「不是量到的」
    assert [x.score for x in out] == [100.0, 0.0, 0.0, 100.0]
    assert [x.width for x in out] == [4.0, 0.0, 0.0, 4.0]


def test_interpolate_missing_needs_both_ends_verified():
    with pytest.raises(ValueError):
        interpolate_missing([_lm(0.0), None, None])


def test_three_steps_compose_back_to_find_vertical_lines_grid():
    """拆出来的三步手工串起来 = 整函数，逐位相同（`_snap_to_inner_rule` 在本合成页
    上不动手：最外两条半高宽 3，远小于 BAR_WIDTH_MIN=12）。"""
    mask = _page()
    whole, whole_filled = find_vertical_lines_grid(mask, n_lines=N_COLS + 1)
    pool, bank = _vline_pool(mask, 60, 90, 200, 0.5, 3)
    a, b = select_frame_pair(pool, N_COLS + 1)
    parts, parts_filled = interpolate_missing(verify_slots(mask, a, b, N_COLS + 1, bank))
    assert parts_filled == whole_filled
    assert [x.position for x in parts] == [x.position for x in whole]
    assert [x.slope for x in parts] == [x.slope for x in whole]


def test_grid_thresholds_without_priors_are_the_calibrated_absolutes():
    """两个先验都不给 → 原样返回北行日錄那组标定值，与加这套之前逐位相同。"""
    from open_guji_cv.utils.peak_line_search import (
        GRID_MAX_WIDTH, GRID_MIN_SCORE, GRID_PITCH_TOL, GRID_SLOT_TOL, grid_thresholds,
    )
    assert grid_thresholds() == {"pitch_tol_frac": GRID_PITCH_TOL, "slot_tol": GRID_SLOT_TOL,
                                 "max_width": GRID_MAX_WIDTH, "min_score": GRID_MIN_SCORE}
    # 传本书自己的标定值 = 恒等（比例 1.0）
    from open_guji_cv.utils.peak_line_search import GRID_REF_FRAME_H, GRID_REF_PITCH
    assert grid_thresholds(GRID_REF_PITCH, GRID_REF_FRAME_H) == grid_thresholds()


def test_grid_thresholds_scale_with_resolution():
    """分辨率减半 → 横向尺度（slot_tol / max_width）跟列距减半，
    min_score 跟框高减半。换书不重标这几个数**不报错、只静默退化**。"""
    from open_guji_cv.utils.peak_line_search import (
        GRID_MAX_WIDTH, GRID_MIN_SCORE, GRID_REF_FRAME_H, GRID_REF_PITCH, GRID_SLOT_TOL,
        grid_thresholds,
    )
    half = grid_thresholds(GRID_REF_PITCH / 2, GRID_REF_FRAME_H / 2)
    assert half["slot_tol"] == round(GRID_SLOT_TOL / 2)
    assert half["max_width"] == pytest.approx(GRID_MAX_WIDTH / 2)
    assert half["min_score"] == pytest.approx(GRID_MIN_SCORE / 2)
    # pitch_tol_frac 无量纲，不跟着变
    assert half["pitch_tol_frac"] == grid_thresholds()["pitch_tol_frac"]


def test_grid_thresholds_accepts_one_prior_at_a_time():
    """只给列距 → 只换横向两个；只给框高 → 只换 min_score。缺哪个留哪个的缺省。"""
    from open_guji_cv.utils.peak_line_search import (
        GRID_MIN_SCORE, GRID_REF_FRAME_H, GRID_REF_PITCH, GRID_SLOT_TOL, grid_thresholds,
    )
    only_pitch = grid_thresholds(col_pitch=GRID_REF_PITCH * 2)
    assert only_pitch["slot_tol"] == GRID_SLOT_TOL * 2
    assert only_pitch["min_score"] == GRID_MIN_SCORE          # 没给框高就不动
    only_h = grid_thresholds(frame_height=GRID_REF_FRAME_H * 2)
    assert only_h["slot_tol"] == GRID_SLOT_TOL                # 没给列距就不动
    assert only_h["min_score"] == pytest.approx(GRID_MIN_SCORE * 2)


def test_detect_borders_frame_height_is_opt_in():
    """`frame_height` 不传 = 加这套之前的行为，逐位相同。"""
    gray = np.where(_page() > 0, 0.0, 255.0)
    a = detect_borders(gray, expected_cols=N_COLS, column_grid=True, col_pitch=PITCH)
    b = detect_borders(gray, expected_cols=N_COLS, column_grid=True, col_pitch=PITCH,
                       frame_height=None)
    assert [v.x_at_top for v in a.verticals] == [v.x_at_top for v in b.verticals]
    assert a.vline_filled == b.vline_filled


def test_stretched_frame_pair_pushes_far_slots_out_of_tolerance():
    """**网格模式不是自由模式的超集**的机理测（四庫總目 vol02/3 实测的合成复现）：
    版框对一端落在比真末线更靠外的东西上（那一页是粗外框，这里用页边假线代替），
    隐含列距被拉伸，漂移沿槽位线性累积，末几槽超出 `slot_tol` 就验不上——
    于是**明明印着线却被插值**。病因在选对那一步，症状在插值那一步。"""
    mask = _page(missing=set(), humps=())
    pool, bank = _vline_pool(mask, 60, 90, 200, 0.5, 3)
    a = next(r for r in pool if abs(r.position - XS_ALL[0]) <= 2)
    bad_b = next(r for r in pool if abs(r.position - PAGE_EDGE) <= 3)
    stretched = (bad_b.position - a.position) / N_COLS
    assert stretched > PITCH                       # 被拉伸了
    lines = verify_slots(mask, a, bad_b, N_COLS + 1, bank)
    missed = [i for i, ln in enumerate(lines) if ln is None]
    assert missed, "拉伸的版框对应当让末几槽验不上"
    # 漂移线性累积：最先失败的槽，其理论漂移已超出容差
    from open_guji_cv.utils.peak_line_search import GRID_SLOT_TOL
    assert (stretched - PITCH) * missed[0] > GRID_SLOT_TOL
    # 而正确的版框对全槽验得上
    good_b = next(r for r in pool if abs(r.position - XS_ALL[-1]) <= 2)
    assert all(ln is not None for ln in verify_slots(mask, a, good_b, N_COLS + 1, bank))
