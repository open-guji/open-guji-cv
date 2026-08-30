"""border_geometry 单测：新坐标系(右上角原点/从右到左/从1开始)转换 + 整页探测。"""
import numpy as np

from open_guji_cv.utils.border_geometry import (
    HLine,
    VLine,
    _hline_to_new,
    _vline_to_new,
    detect_borders,
)
from open_guji_cv.utils.peak_line_search import LineMatch


def test_vline_to_new_flips_x_and_slope_no_tilt():
    """无倾斜的竖直线：旧坐标 x_old=100(左上角原点)，页宽300 -> 新坐标
    x_at_top 应该是 300-1-100=199，斜率不变(0翻转还是0)。"""
    m = LineMatch(position=100.0, slope=0.0, score=1.0, width=1.0, proj=1.0)
    v = _vline_to_new(m, w=300, h=400)
    assert abs(v.x_at_top - 199.0) < 1e-6
    assert abs(v.slope - 0.0) < 1e-9


def test_vline_to_new_reanchors_from_center_to_top_and_flips_slope():
    """旧坐标位置是在 y=h/2 处量的(peak_line_search内部约定)，新坐标要求
    在 y=0(页面顶端)处量——斜线在这两个锚点的x值不一样，必须先换算旧坐标
    在y=0处的x，再翻转成新坐标；斜率方向也要翻转(x轴反向)。"""
    h = 400
    m = LineMatch(position=150.0, slope=0.02, score=1.0, width=1.0, proj=1.0)
    # 旧坐标在 y=0 处的 x：150 + 0.02*(0-200) = 150-4 = 146
    v = _vline_to_new(m, w=300, h=h)
    expected_x_at_top = (300 - 1) - 146.0
    assert abs(v.x_at_top - expected_x_at_top) < 1e-6
    assert abs(v.slope - (-0.02)) < 1e-9


def test_hline_to_new_reanchors_from_center_to_right_and_flips_slope():
    w = 300
    m = LineMatch(position=50.0, slope=0.01, score=1.0, width=1.0, proj=1.0)
    # 旧坐标在 x_old=w-1=299 处的 y：50 + 0.01*(299-150) = 50+1.49 = 51.49
    h = _hline_to_new(m, w, kind="top")
    assert abs(h.y_at_right - 51.49) < 1e-6
    assert abs(h.slope - (-0.01)) < 1e-9
    assert h.kind == "top"


def test_hline_and_vline_y_at_x_at_roundtrip_consistent_with_old_line():
    """新坐标线在任意点求值，跟旧坐标线在对应点(x_new换算回x_old)求值
    应该完全一致——这是坐标转换正确性最直接的检验：同一条物理线，换个
    坐标系描述，同一物理点上量出来的y(或x)必须一样。"""
    w, h = 300, 400
    m = LineMatch(position=120.0, slope=0.03, score=1.0, width=1.0, proj=1.0)
    v = _vline_to_new(m, w, h)
    for y in (0, 50, 200, 399):
        x_old = m.position + m.slope * (y - h / 2.0)
        x_new_expected = (w - 1) - x_old
        assert abs(v.x_at(y) - x_new_expected) < 1e-6

    mh = LineMatch(position=60.0, slope=-0.02, score=1.0, width=1.0, proj=1.0)
    hl = _hline_to_new(mh, w, kind="bottom")
    for x_new in (0, 50, 150, 299):
        x_old = (w - 1) - x_new
        y_expected = mh.position + mh.slope * (x_old - w / 2.0)
        assert abs(hl.y_at(x_new) - y_expected) < 1e-6


def test_vline_from_endpoints_matches_manual_conversion():
    """标注工具采集的是"这条线上任意两点(标准像素坐标)"——不要求手柄
    落在图像上下边缘(实际标注页手柄放在 8%/92% 高度处)。用 y=0/h-1
    这个特例验证跟旧版本行为一致。"""
    w, h = 300, 400
    x_top, x_bottom = 120.0, 132.0  # 标准坐标：上端x=120，下端x=132，向下微斜
    v = VLine.from_endpoints(x_top, 0, x_bottom, h - 1, w)
    x_old_at_0 = (w - 1) - v.x_at(0)
    x_old_at_h1 = (w - 1) - v.x_at(h - 1)
    assert abs(x_old_at_0 - x_top) < 1e-6
    assert abs(x_old_at_h1 - x_bottom) < 1e-6


def test_vline_from_endpoints_works_with_arbitrary_points_not_at_edges():
    """手柄在图像内部任意两点(不在y=0/h-1)也应该算出同一条线。"""
    w, h = 300, 400
    # 构造一条真实线：x_old(y) = 50 + 0.02*y，取 y=100 和 y=300 两个内部点
    y_a, y_b = 100.0, 300.0
    x_a, x_b = 50 + 0.02 * y_a, 50 + 0.02 * y_b
    v = VLine.from_endpoints(x_a, y_a, x_b, y_b, w)
    for y in (0, 100, 300, 399):
        x_old_expected = 50 + 0.02 * y
        assert abs(((w - 1) - v.x_at(y)) - x_old_expected) < 1e-6


def test_hline_from_endpoints_matches_manual_conversion():
    w = 300
    y_left, y_right = 40.0, 45.0  # 标准坐标：左端y=40(x=0)，右端y=45(x=w-1)
    h = HLine.from_endpoints(0, y_left, w - 1, y_right, w, kind="top")
    # 新坐标 x_new=0 对应标准坐标最右端(x_old=w-1)，其y值就是y_right
    assert abs(h.y_at(0) - y_right) < 1e-6
    # 新坐标 x_new=w-1 对应标准坐标最左端(x_old=0)，其y值就是y_left
    assert abs(h.y_at(w - 1) - y_left) < 1e-6


def test_hline_from_endpoints_works_with_arbitrary_points_not_at_edges():
    w = 300
    x_a, x_b = 30.0, 200.0
    y_a, y_b = 40.0, 47.0  # y_old(x) = 40 + (7/170)*(x-30)
    h = HLine.from_endpoints(x_a, y_a, x_b, y_b, w, kind="bottom")
    for x_old in (0, 30, 200, w - 1):
        y_expected = y_a + (y_b - y_a) / (x_b - x_a) * (x_old - x_a)
        x_new = (w - 1) - x_old
        assert abs(h.y_at(x_new) - y_expected) < 1e-6


def _draw_tilted_vline(mask, x_old_at_top, slope, half_width=2):
    h = mask.shape[0]
    for y in range(h):
        x = int(round(x_old_at_top + slope * y))
        lo, hi = max(0, x - half_width), min(mask.shape[1], x + half_width + 1)
        if lo < hi:
            mask[y, lo:hi] = 1.0


def test_detect_borders_orders_verticals_right_to_left_in_new_coords():
    """9列的整页合成图：新坐标系输出的 verticals 应该按物理位置从右到左
    排列(verticals[0]是最右列的外边框，x_at_top应该是所有线里最小的)。"""
    h, w = 500, 1000
    gray = np.full((h, w), 255.0)
    n_cols = 9
    # 10条竖直线(9列)，旧坐标里从左到右等距分布，模拟真实版面
    xs_old = np.linspace(80, w - 80, n_cols + 1)
    mask_bin = np.zeros((h, w), dtype=np.uint8)
    for x_old in xs_old:
        _draw_tilted_vline(mask_bin, x_old, slope=0.0, half_width=3)
    # 顶/底加两条横线(窄带内)
    mask_bin[40:44, :] = 1
    mask_bin[h - 44:h - 40, :] = 1
    gray = np.where(mask_bin > 0, 0.0, 255.0)

    result = detect_borders(gray, expected_cols=n_cols)
    assert len(result.verticals) == n_cols + 1
    xs_new = [v.x_at_top for v in result.verticals]
    assert xs_new == sorted(xs_new)  # 已按x_at_top升序，即物理从右到左
    # 最右一条线(verticals[0])对应旧坐标里x最大的那条
    assert result.verticals[0].x_at_top < result.verticals[-1].x_at_top
    expected_rightmost_x_new = (w - 1) - xs_old[-1]
    expected_leftmost_x_new = (w - 1) - xs_old[0]
    assert abs(result.verticals[0].x_at_top - expected_rightmost_x_new) < 15
    assert abs(result.verticals[-1].x_at_top - expected_leftmost_x_new) < 15
    assert result.head_raise == []  # 抬头目前没有自动探测，默认空
