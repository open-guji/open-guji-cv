"""peak_line_search 单测：半高宽匹配度 + 位置角度联合搜索，用合成图验证。"""
import numpy as np

from open_guji_cv.utils.peak_line_search import (
    LineMatch,
    _dedup_by_position,
    _sample_line_curve_naive,
    _shift_blocks,
    find_horizontal_border,
    half_height_score_at,
    joint_search_coarse_to_fine,
    projection,
    sample_line_curve,
)

H, W = 400, 300


def _blank_mask():
    return np.zeros((H, W), dtype=np.float64)


def test_half_height_score_prefers_narrow_over_wide_peak():
    """窄尖峰的匹配度应明显高于同等高度的宽驼峰（界行 vs 正文列）。"""
    narrow = np.zeros(200)
    narrow[95:100] = 800.0  # 5px 宽的尖峰
    wide = np.zeros(200)
    wide[50:150] = 800.0    # 100px 宽的平台（正文列密度）

    _, score_narrow = half_height_score_at(narrow, 97)
    _, score_wide = half_height_score_at(wide, 100)
    assert score_narrow > score_wide * 5


def test_half_height_tolerates_small_dip_in_peak():
    """峰内一个小凹陷（笔画间隙）不该被判成"跌出峰"。"""
    curve = np.zeros(60)
    curve[25:35] = 900.0
    curve[29] = 900.0 * 0.55  # 单点小凹陷，仍在半高阈值以上
    width, score = half_height_score_at(curve, 30)
    assert width <= 12  # 没有因为这一个凹陷被切断成两段更窄的峰
    assert score > 50


def test_joint_search_recovers_straight_vertical_line():
    """一条无倾斜的竖直线：联合搜索应该找回原始位置、倾角≈0。"""
    mask = _blank_mask()
    true_x = 150
    mask[:, true_x - 2:true_x + 3] = 1.0  # 5px 宽的竖直墨线
    best = joint_search_coarse_to_fine(mask, "v", true_x - 30, true_x + 30)
    assert abs(best.position - true_x) <= 2
    assert abs(best.slope) < 0.01
    assert best.score > 20


def test_joint_search_recovers_tilted_line_position_and_angle():
    """一条倾斜的竖直线，初始候选位置(naive x0)跟真实锚点差了一截——
    这正是实测中 vol02/133 x=33/216 那两条线的情形：固定位置只搜角度会找错，
    联合搜索应该找对。"""
    mask = _blank_mask()
    true_slope = 0.05  # 明显倾斜
    true_anchor = 130  # 真实位置：直线在 y_center 处的 x
    y_center = H / 2.0
    for y in range(H):
        x = int(round(true_anchor + true_slope * (y - y_center)))
        if 0 <= x - 2 and x + 2 < W:
            mask[y, x - 2:x + 3] = 1.0

    naive_x0 = 118  # 粗投影给出的初始猜测，故意跟真实锚点差 12px
    best = joint_search_coarse_to_fine(mask, "v", naive_x0 - 40, naive_x0 + 40,
                                        coarse_range=0.08, coarse_n=17,
                                        fine_radius=0.01, fine_n=21)
    assert abs(best.position - true_anchor) <= 3
    assert abs(best.slope - true_slope) < 0.01
    assert best.score > 20

    # 对照：把位置锁死在 naive_x0、只搜角度——这是早期版本的 bug。位置锁死后
    # 怎么调角度都碰不到真实的线，捕到的墨量应该远低于联合搜索（后者几乎
    # 捕全了这条线的墨）。防止回归。
    from open_guji_cv.utils.peak_line_search import sample_line_curve, half_height_score_at as hh
    locked_best_proj = -1.0
    for s in np.linspace(-0.08, 0.08, 33):
        _, curve = sample_line_curve(mask, "v", naive_x0, naive_x0, float(s))
        wd, sc = hh(curve, 0)
        locked_best_proj = max(locked_best_proj, curve[0])
    assert best.proj > locked_best_proj * 3


def test_projection_axis_v_and_h_are_transposes():
    mask = _blank_mask()
    mask[10:20, 30:35] = 1.0
    col = projection(mask, "v")
    row = projection(mask, "h")
    assert col[32] == 10  # 该列 10 行都是墨
    assert row[15] == 5   # 该行 5 列都是墨


def test_find_horizontal_border_prefers_secondary_closer_to_center():
    """整带最强峰是"离中心更远"的干扰（抬头装饰墨迹/外边框），真正的内
    边框是窗口内次强但离中心更近的候选——应该换成次强候选。对应实测里
    vol01/49 顶部（装饰墨迹分数比边框还高）和 vol01/137、138 底部（外边框
    分数比内边框高）两类失败模式的最小复现。"""
    mask = _blank_mask()
    decoy_y, true_y = 12, 45  # 都在 top 搜索带(0..~60)内，间距33px < 60px窗口
    mask[decoy_y - 2:decoy_y + 3, :] = 1.0        # 离中心更远，分数更高
    mask[true_y - 2:true_y + 3, :150] = 1.0        # 离中心更近，分数较低但 ratio>0.2

    result = find_horizontal_border(mask, "top", band_frac=0.2)
    assert abs(result.position - true_y) <= 3


def _lm(position, score):
    return LineMatch(position=position, slope=0.0, score=score, width=5.0, proj=score * 5)


def test_dedup_by_position_drops_weaker_of_close_pair():
    """相邻窗口切在同一条真实线中间时，两侧各自会精修出一条位置接近的线
    （vol01/141 实测：x≈1633 和 x≈1648，相隔15px<min_dist），应该只保留
    分数更高的那条，不是两条都留。"""
    results = [_lm(100, 50), _lm(1633, 273.3), _lm(1648, 255.8), _lm(2005, 140.3)]
    deduped = _dedup_by_position(results, min_dist=60)
    positions = sorted(r.position for r in deduped)
    assert positions == [100, 1633, 2005]


def test_dedup_by_position_keeps_all_when_well_separated():
    results = [_lm(100, 50), _lm(300, 80), _lm(500, 60)]
    deduped = _dedup_by_position(results, min_dist=60)
    assert len(deduped) == 3


def test_find_horizontal_border_rejects_secondary_farther_from_center():
    """回归护栏：primary 已经是正确的边框（离中心更近），窗口内即使有个分数
    相近甚至更高的候选，只要它离中心更远（比如抬头页顶部一坨强墨迹、或者
    比 primary 更靠外的另一条线），也不该被换上去——防止重蹈"整带最强峰
    优先"式的过度纠正（这条护栏对应之前一次失败尝试：宽范围搜索+离中心
    最近，把好几个本来正确的页面带崩了）。"""
    mask = _blank_mask()
    true_y, far_decoy_y = 45, 12  # true 离中心更近，far_decoy 离中心更远
    mask[true_y - 2:true_y + 3, :] = 1.0            # 主峰，应该保留
    mask[far_decoy_y - 2:far_decoy_y + 3, :148] = 1.0  # 窗口内、分数稍弱、但离中心更远

    result = find_horizontal_border(mask, "top", band_frac=0.2)
    assert abs(result.position - true_y) <= 3


# ── 分块 BLAS 采样：跟朴素花式索引实现的等价性护栏 ──────────────


def test_shift_blocks_cover_all_rows_and_are_contiguous():
    """分块采样成立的前提：整数位移相同的行必须是**连续**区间，且不重不漏。"""
    for n, slope in ((3077, 0.05), (3077, -0.05), (400, 0.0071), (37, -1e-9), (60, 0.0)):
        blocks = _shift_blocks(n, slope)
        assert blocks[0][0] == 0 and blocks[-1][1] == n
        for (a, b, _), (c, _, _) in zip(blocks, blocks[1:]):
            assert a < b == c                      # 首尾相接、不重不漏
        t = np.arange(n, dtype=np.float64)
        want = np.floor(slope * (t - n / 2.0)).astype(np.int64)
        for a, b, k in blocks:
            assert (want[a:b] == k).all()


def test_sample_line_curve_matches_naive_reference():
    """分块 BLAS 实现必须跟朴素 gather 实现在数值上一致（求和次序不同，只允许
    浮点级差）。两个方向、越界窗口、空窗口、正负倾角都要覆盖。

    唯一的例外是朴素实现自己的 clip 瑕疵：它先 `clip(coord, 0, limit-1.001)`
    再 `floor`，`coord` 落进 [limit-1.001, limit-1) 这条 0.001px 宽的缝时会把
    0.1% 的权重错挪一列。真实倾角网格下够不着，所以这里只测真实倾角。"""
    rng = np.random.default_rng(0)
    slopes = list(np.linspace(-0.05, 0.05, 9)) + [0.0071, -0.0123]
    for shape in ((37, 29), (60, 60), (11, 53)):
        mask = (rng.random(shape) < 0.3).astype(np.float64)
        h, w = shape
        for axis, limit in (("v", w), ("h", h)):
            for lo, hi in [(0, limit - 1), (-20, limit + 19), (-5, 3),
                           (limit - 4, limit + 9), (7, 7), (10, 4)]:
                for s in slopes:
                    pn, cn = _sample_line_curve_naive(mask, axis, lo, hi, float(s))
                    pb, cb = sample_line_curve(mask, axis, lo, hi, float(s))
                    assert pn.shape == pb.shape and cn.shape == cb.shape
                    if cn.size:
                        assert np.abs(cn - cb).max() < 1e-9


def test_sample_line_curve_far_edge_weight_is_not_clipped():
    """朴素实现在最外沿有 0.1% 的权重错挪（clip 到 limit-1.001 再 floor），
    分块实现给的是真值。这条钉住的是「分块版更对」，不是「两版一样」。"""
    mask = np.zeros((4, 6))
    mask[:, 5] = 1.0
    _, naive = _sample_line_curve_naive(mask, "v", 0, 5, -1e-9)
    _, block = sample_line_curve(mask, "v", 0, 5, -1e-9)
    assert abs(naive[5] - 0.999) < 1e-9            # 0.1% 被挪到了第 4 列（那列没墨）
    assert abs(block[5] - 1.0) < 1e-6              # 真值：该行的墨全在第 5 列
