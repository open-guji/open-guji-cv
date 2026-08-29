"""row_boundaries 单测：波谷/空白探测、周期估计、弹性 DP，用合成投影曲线验证。"""
import numpy as np

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


def test_fit_row_boundaries_returns_none_when_not_enough_candidates():
    # 太短的曲线撑不出 21 个格子
    curve = _synth_column(n_chars=2, lead_blank_slots=0)
    result = fit_row_boundaries(curve, DST_W, 0.0, float(len(curve) - 1),
                                 period=GAP, n_slots=21)
    assert result is None
