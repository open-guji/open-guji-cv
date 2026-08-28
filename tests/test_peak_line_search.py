"""peak_line_search 单测：半高宽匹配度 + 位置角度联合搜索，用合成图验证。"""
import numpy as np

from open_guji_cv.utils.peak_line_search import (
    half_height_score_at,
    joint_search_coarse_to_fine,
    projection,
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
