"""row_boundaries 单测：波谷/空白探测、周期估计、弹性 DP，用合成投影曲线验证。"""
import numpy as np

from open_guji_cv.utils import row_boundaries as fit_mod
from open_guji_cv.utils.row_boundaries import (
    estimate_period,
    estimate_shared_period,
    find_blank_intervals,
    find_valleys,
    fit_row_boundaries,
    smooth_curve,
    trim_content_span,
)

DST_W = 180
GAP = 110


def _synth_column(n_chars: int, gap: float = GAP, dst_w: int = DST_W,
                   lead_blank_slots: int = 2, noise_valleys: bool = False) -> np.ndarray:
    """造一列合成投影：lead_blank_slots 个空白格 + n_chars 个"字"（每字中间
    墨量高、字缝处墨量趋近 0），字缝处叠一点小凹陷噪声(可选)模拟笔画间隙。

    每个字画在自己那个格子的正中央(格子 slot_idx 的中心 = slot_idx*gap +
    gap/2)，这样"第 m 条真实边界应该在 y≈m*gap"这个断言可以直接跟构造对上，
    不用另外换算偏移。"""
    total_slots = lead_blank_slots + n_chars
    length = int(total_slots * gap) + 20
    curve = np.zeros(length)
    for k in range(n_chars):
        center = int((lead_blank_slots + k) * gap + gap / 2)
        for dy in range(-int(gap * 0.4), int(gap * 0.4)):
            y = center + dy
            if 0 <= y < length:
                curve[y] = max(curve[y], dst_w * 0.9 * (1 - (dy / (gap * 0.4)) ** 2))
        if noise_valleys:
            # 字身内部人为戳几个笔画间隙的小凹陷（真实数据里很常见的干扰）
            for off in (-15, 10):
                y = center + off
                if 0 <= y < length:
                    curve[y] *= 0.5
    return curve


def test_find_valleys_recovers_char_gaps_and_ignores_stroke_noise():
    curve = _synth_column(n_chars=5, noise_valleys=True)
    smoothed = smooth_curve(curve)
    valleys = find_valleys(smoothed, DST_W)
    # 5个字之间应该有真实的字缝波谷，笔画噪声(墨量打对折，仍然不低)不该被
    # 当成波谷选中
    assert len(valleys) >= 4
    assert len(valleys) < 15  # 没有被笔画噪声灌满


def test_find_blank_intervals_detects_leading_blank_and_ignores_short_dips():
    curve = _synth_column(n_chars=3, lead_blank_slots=2)
    smoothed = smooth_curve(curve)
    thresh = 0.08 * DST_W
    intervals = find_blank_intervals(smoothed, thresh, min_width=25)
    assert len(intervals) >= 1
    lo, hi = intervals[0]
    assert lo < 20  # 从曲线开头就是空白
    assert hi - lo > 2 * GAP * 0.5  # 覆盖了两个空白格的量级


def test_trim_content_span_skips_border_ink_spike():
    curve = _synth_column(n_chars=3, lead_blank_slots=2)
    # 版框线自己的墨量尖峰，紧贴 x1——不跳过这几像素会让 trim 直接失效
    curve[0:6] = DST_W * 0.9
    thresh = 0.08 * DST_W
    content_start, content_end = trim_content_span(curve, x1=0, x2=len(curve) - 1,
                                                     thresh=thresh, border_margin=15)
    # 应该跳过开头的版框尖峰和后续的真实空白，落在第一个字身附近
    first_char_start = int(2 * GAP + GAP / 2 - GAP * 0.4)
    assert abs(content_start - first_char_start) < GAP * 0.6


def test_estimate_period_recovers_synthetic_gap():
    curve = _synth_column(n_chars=8, gap=GAP, lead_blank_slots=0)
    smoothed = smooth_curve(curve)
    period = estimate_period(smoothed, lag_lo=70, lag_hi=160)
    assert abs(period - GAP) <= 6


def test_estimate_shared_period_uses_median_across_columns():
    curves = [_synth_column(n_chars=6, gap=g) for g in (105, 108, 110, 112, 150)]
    borders = [(0.0, float(len(c) - 1)) for c in curves]
    dst_ws = [DST_W] * len(curves)
    p = estimate_shared_period(curves, borders, dst_ws)
    # 中位数应该落在正常那几列的范围内，不被最后一列的离群周期(150)拖走
    assert 100 <= p <= 118


def test_fit_row_boundaries_recovers_char_slots_on_clean_synthetic_column():
    n_chars = 6
    lead = 2
    n_slots = lead + n_chars
    curve = _synth_column(n_chars=n_chars, lead_blank_slots=lead)
    border_top, border_bottom = 0.0, float(len(curve) - 1)
    result = fit_row_boundaries(curve, DST_W, border_top, border_bottom,
                                 period=GAP, n_slots=n_slots)
    assert result is not None
    assert len(result.boundaries) == n_slots + 1
    # 边界应该单调递增
    assert all(b2 > b1 for b1, b2 in zip(result.boundaries, result.boundaries[1:]))
    # 每个真实字缝(第 lead+1 .. n_slots-1 个边界)应该落在对应字缝的合理范围内
    for k in range(lead + 1, n_slots):
        expected = k * GAP
        assert abs(result.boundaries[k] - expected) < GAP * 0.5


def test_fit_row_boundaries_top_slack_recovers_content_above_border_top():
    """模拟"抬头列"最简单的一种失败：探测到的版框位置(border_top)本身落在
    本该属于开头空白格的区域里(抬头把首字往上顶，边框相对内容的"有效位置"
    就往后退了)——不给 top_slack，起点窗口卡在 border_top 之后，找不到能
    撑满 n_slots 个格子的候选，直接判无解(比瞎猜一个錯误位置更安全)；给了
    top_slack 放宽起点窗口下界，才能把第 0 个边界点找回真正的内容起点。"""
    n_chars = 4
    lead = 2
    n_slots = lead + n_chars
    curve = _synth_column(n_chars=n_chars, lead_blank_slots=lead)
    border_bottom = float(len(curve) - 1)
    fake_border_top = 1.3 * GAP  # 探测到的版框位置落进了本该是开头空白格的区间

    no_slack = fit_row_boundaries(curve, DST_W, fake_border_top, border_bottom,
                                   period=GAP, n_slots=n_slots)
    assert no_slack is None

    with_slack = fit_row_boundaries(curve, DST_W, fake_border_top, border_bottom,
                                     period=GAP, n_slots=n_slots, top_slack=2 * GAP)
    assert with_slack is not None
    assert len(with_slack.boundaries) == n_slots + 1
    assert abs(with_slack.boundaries[0] - 0.0) < GAP * 0.3


def test_fit_row_boundaries_returns_none_when_not_enough_candidates():
    # 太短的曲线撑不出 21 个格子
    curve = _synth_column(n_chars=2, lead_blank_slots=0)
    result = fit_row_boundaries(curve, DST_W, 0.0, float(len(curve) - 1),
                                 period=GAP, n_slots=21)
    assert result is None


# ── Step 3 正门：列图 → 带类型的字格 ──────────────────────────

COL_W = 185          # 列距量级（vol02 实测 184px）
SLOT_H = 110         # 字距量级
N_SLOTS = 21
GRID_Y0 = 10         # 网格起点（版框线到第一格顶还有一点偏移）
RULE_W = 4           # 两侧界行的宽度


def _synth_column_image(jiazhu_slots=(), blank_slots=(), n_slots=N_SLOTS,
                         top_border_y=0, draw_rules=True):
    """造一张 Step 2 那样的矫正后列图（白底、界行贴在两侧、格里画墨块）。

    `top_border_y`：上版框横线画在这一行（抬头列把它往下挪，让首格落到线上方）。
    """
    h = GRID_Y0 + n_slots * SLOT_H + 20
    img = np.full((h, COL_W), 255, dtype=np.uint8)
    if draw_rules:                      # 界行：贯穿全高的两堵墙
        img[:, :RULE_W] = 0
        img[:, -RULE_W:] = 0
    img[top_border_y:top_border_y + 4, :] = 0        # 上版框
    img[h - 4:, :] = 0                                # 下版框
    for k in range(n_slots):
        slot = k + 1
        if slot in blank_slots:
            continue
        y0 = GRID_Y0 + k * SLOT_H + 10
        y1 = y0 + 90
        if slot in jiazhu_slots:        # 双列小字：缝在列心，两侧各一个小字
            img[y0:y1, 15:85] = 0
            img[y0:y1, 100:COL_W - 15] = 0
        else:                            # 正文字：居中，跨度只占 0.6 列距
            img[y0:y1, 37:148] = 0
    return img


def _kinds(result):
    return {c.slot: c.kind for c in result.cells if c.sub is None}


def test_find_content_window_strips_the_rules_on_both_sides():
    img = _synth_column_image()
    pad = 3     # find_content_window 的默认安全余量（界行的墨是渐弱的）
    x_lo, x_hi = fit_mod.find_content_window(img)
    assert x_lo == RULE_W + pad
    assert x_hi == COL_W - RULE_W - pad


def test_find_content_window_is_a_noop_without_rules():
    img = _synth_column_image(draw_rules=False)
    assert fit_mod.find_content_window(img) == (0, COL_W)


def test_segment_column_types_plain_and_blank_cells():
    img = _synth_column_image(blank_slots=(5, 6))
    r = fit_mod.segment_column(img, period=SLOT_H, n_slots=N_SLOTS)
    assert r is not None
    kinds = _kinds(r)
    assert kinds[5] == "blank" and kinds[6] == "blank"
    assert all(kinds[s] == "char" for s in kinds if s not in (5, 6))
    # 切分点应该落在真实格线上（真值 = GRID_Y0 + k*SLOT_H）
    err = [abs(b - (GRID_Y0 + k * SLOT_H)) for k, b in enumerate(r.boundaries)]
    # 空白段里没有真实字缝，只能靠 synth_step 撒的合成候选撑住可行性，精度
    # 天然差一档（已知局限，见模块头）——这里 4~6 号点正是空白格 5/6 的边界
    assert max(err[:4] + err[7:]) < 12, err
    assert max(err) < 25, err
    # 格框的 x 范围是剥掉界行之后的内容窗口，不是整张列图
    x_lo, x_hi = fit_mod.find_content_window(img)
    assert r.content_x == (x_lo, x_hi)
    assert all(c.x0 == x_lo and c.x1 == x_hi for c in r.cells)


def test_segment_column_splits_jiazhu_run_into_a_and_b_halves():
    img = _synth_column_image(jiazhu_slots=(8, 9, 10, 11))
    r = fit_mod.segment_column(img, period=SLOT_H, n_slots=N_SLOTS, ref_w=COL_W)
    assert r is not None
    jz = {}
    for c in r.cells:
        if c.sub:
            jz.setdefault(c.slot, {})[c.sub] = c
    assert sorted(jz) == [8, 9, 10, 11]
    for slot, halves in jz.items():
        assert sorted(halves) == ["a", "b"]
        a, b = halves["a"], halves["b"]
        assert a.kind == "jiazhu_a" and b.kind == "jiazhu_b"
        assert b.x1 == a.x0                          # 两半在同一条缝上切开
        assert a.gap_center == b.gap_center           # 缝中心两半共用
        assert abs(a.x0 - a.gap_center) <= 0.5       # 切在缝中心（取整到像素）
        assert (b.x0, a.x1) == r.content_x            # 两半合起来是整格
        assert a.y0 == b.y0 and a.y1 == b.y1
    # 孤立的左右结构字判不成夹注（MIN_RUN），其余格仍是正文字
    assert all(k == "char" for s, k in _kinds(r).items() if s not in jz)


def test_segment_column_reading_order_is_all_a_then_all_b_within_a_run():
    img = _synth_column_image(jiazhu_slots=(8, 9, 10))
    r = fit_mod.segment_column(img, period=SLOT_H, n_slots=N_SLOTS, ref_w=COL_W)
    seq = [(c.slot, c.sub) for c in sorted(r.cells, key=lambda c: c.order)]
    assert seq[:7] == [(s, None) for s in range(1, 8)]
    assert seq[7:13] == [(8, "a"), (9, "a"), (10, "a"),
                         (8, "b"), (9, "b"), (10, "b")]
    assert seq[13] == (11, None)
    # order 是本列一条完整的 1..N 序，没有空号也没有重号
    assert sorted(c.order for c in r.cells) == list(range(1, len(r.cells) + 1))


def test_segment_column_detect_jiazhu_off_keeps_whole_cells():
    img = _synth_column_image(jiazhu_slots=(8, 9, 10, 11))
    r = fit_mod.segment_column(img, period=SLOT_H, n_slots=N_SLOTS, ref_w=COL_W,
                               detect_jiazhu=False)
    assert all(c.sub is None for c in r.cells)
    assert len(r.cells) == N_SLOTS


def test_segment_column_marks_cells_above_the_top_border_as_raised():
    """抬头列：Step 2 多矫正了一截页顶（列图顶端那条线是这一列自己的抬头框），
    页面主版框在列图里的 y 由调用方告诉 Step 3；首格落到它上面 → 标 raised。"""
    img = _synth_column_image()          # 顶端那条线 = 抬头框，网格从 y=10 起
    r = fit_mod.segment_column(img, period=SLOT_H, n_slots=N_SLOTS,
                               border_top=60.0,      # 主版框在列图里的位置
                               top_slack=SLOT_H)
    assert r is not None
    kinds = _kinds(r)
    assert kinds[1] == "raised"
    assert all(k == "char" for s, k in kinds.items() if s != 1)


def test_segment_column_returns_none_when_dp_has_no_solution():
    img = _synth_column_image()
    # 只有 21 格的信号，硬要切 40 格：候选撑不出来，应当判无解而不是给错结果
    assert fit_mod.segment_column(img, period=SLOT_H, n_slots=40) is None
