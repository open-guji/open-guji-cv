"""border_geometry 单测：新坐标系(右上角原点/从右到左/从1开始)转换 + 整页探测。"""
import numpy as np

from open_guji_cv.utils.border_geometry import (
    HLine,
    VLine,
    _hline_to_new,
    _vline_to_new,
    detect_borders,
    detect_head_raise,
    detect_outer_borders,
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


# --- 抬头框探测 ---------------------------------------------------------

def _blank_head_raise_page(w=1000, h=800, n_cols=9, border_top=400):
    """搭一张只有版框+界行的合成页，返回 (mask, top, verticals)。
    抬头框由各测试自己往 mask 上画。"""
    mask = np.zeros((h, w), dtype=np.float64)
    xs_old = np.linspace(80, w - 80, n_cols + 1)
    for x_old in xs_old:
        # 界行只在版框内，主上边框以上是空白——抬头框的竖墙是那片区域里
        # 唯一的竖直墨迹，墙线判据才有意义
        mask[border_top:, int(x_old) - 2:int(x_old) + 3] = 1.0
    mask[border_top:border_top + 5, :] = 1.0          # 主上边框(内)
    mask[border_top - 34:border_top - 30, :] = 1.0    # 主上边框(外)
    top = HLine(y_at_right=float(border_top + 2), slope=0.0, kind="top")
    verticals = [VLine(x_at_top=float((w - 1) - x), slope=0.0) for x in xs_old[::-1]]
    return mask, top, verticals, xs_old


def _paint_raised_box(mask, xs_old, cols, inner_y, outer_y, border_top,
                       outer_thickness=1):
    """把 cols(新坐标列号,从右到左从1开始) 这一块画成抬头：内框细线、
    外框(粗细可调)、两端竖墙落到主边框。"""
    n = len(xs_old) - 1
    # 列号 c 对应的旧坐标区间：[xs_old[n-c], xs_old[n-c+1]]
    lefts = [xs_old[n - c] for c in cols]
    rights = [xs_old[n - c + 1] for c in cols]
    x0, x1 = int(min(lefts)), int(max(rights))
    mask[int(inner_y) - 1:int(inner_y) + 2, x0:x1] = 1.0
    if outer_thickness:
        mask[int(outer_y):int(outer_y) + outer_thickness, x0:x1] = 1.0
    for xw in (x0, x1 - 4):
        mask[int(inner_y):border_top + 3, xw:xw + 5] = 1.0


def test_detect_head_raise_finds_nothing_on_plain_page():
    """普通页：窗口里唯一的细锐线是主边框自己的外框(距主框仅30px)，
    必须被"离主边框 90~210px"这一条挡掉，不能报抬头。"""
    mask, top, verts, _ = _blank_head_raise_page()
    assert detect_head_raise(mask, top, verts, width=1000) == []


def test_detect_head_raise_finds_thick_outer_bar_block():
    """典型形态(vol01/33、26、47 型)：外框是一条粗满墨条，内框是细线。"""
    border_top = 400
    mask, top, verts, xs = _blank_head_raise_page(border_top=border_top)
    _paint_raised_box(mask, xs, cols=[5, 6], inner_y=280, outer_y=244,
                      border_top=border_top, outer_thickness=18)
    got = detect_head_raise(mask, top, verts, width=1000)
    assert sorted(r.col for r in got) == [5, 6]
    for r in got:
        assert abs(r.inner_y - 280) <= 4
        assert abs(r.outer_y - 244) <= 4
        assert r.estimated is False


def test_detect_head_raise_survives_missing_outer_border():
    """vol01/51 型：外框在扫描里根本没印上(墨占比 0.00~0.18)。只有内框
    可见时仍然要报出来，outer 按中位间距推、标 estimated。
    这条是 v3 "必须内外成对"那版召回崩到 28% 的直接原因。"""
    border_top = 400
    mask, top, verts, xs = _blank_head_raise_page(border_top=border_top)
    _paint_raised_box(mask, xs, cols=[3], inner_y=270, outer_y=0,
                      border_top=border_top, outer_thickness=0)
    got = detect_head_raise(mask, top, verts, width=1000)
    assert [r.col for r in got] == [3]
    assert abs(got[0].inner_y - 270) <= 4
    assert got[0].estimated is True


def test_detect_head_raise_block_middle_column_needs_no_own_wall():
    """连续抬头列共用一个抬头框，块内部的界行在抬头区继续延伸、不是墙。
    墙线只能在块的最外两侧查——vol01/33 c7 在块中间，实测墙覆盖率只有
    0.00~0.04，按列查墙会把它误杀。"""
    border_top = 400
    mask, top, verts, xs = _blank_head_raise_page(border_top=border_top)
    _paint_raised_box(mask, xs, cols=[4, 5, 6], inner_y=285, outer_y=249,
                      border_top=border_top, outer_thickness=16)
    got = detect_head_raise(mask, top, verts, width=1000)
    assert sorted(r.col for r in got) == [4, 5, 6]


def test_detect_head_raise_rejects_horizontal_line_without_walls():
    """没有竖直连接墙线的孤立横线(书斑/渗墨/邻页痕)不算抬头。"""
    border_top = 400
    mask, top, verts, xs = _blank_head_raise_page(border_top=border_top)
    n = len(xs) - 1
    x0, x1 = int(xs[n - 6]), int(xs[n - 5])
    mask[279:282, x0:x1] = 1.0
    mask[243:261, x0:x1] = 1.0
    assert detect_head_raise(mask, top, verts, width=1000) == []


# ---------------------------------------------------------------- 外框探测

def _outer_page(w=1000, h=1200, gap=40, top_y=300, bot_y=900,
                 paint_top_outer=True, paint_bottom_outer=True,
                 decoy_top_offset=None, text_below_bottom=False):
    """搭一张有内外双版框的合成页。

    `gap` 是内外框间距——真书上这是个全页常数（14 页实测竖直 38.4±4.0px），
    `detect_outer_borders` 就靠竖直外框把它量出来、再拿去框住上下的搜索窗。
    `decoy_top_offset` 用来在别处再画一条假线，测先验窗口挡不挡得住。
    """
    mask = np.zeros((h, w), dtype=np.float64)
    xs_old = np.linspace(150, w - 150, 10)
    for x_old in xs_old:
        mask[top_y:bot_y, int(x_old) - 2:int(x_old) + 3] = 1.0
    mask[top_y:top_y + 5, :] = 1.0
    mask[bot_y - 5:bot_y, :] = 1.0
    # 竖直外框只在纸边一侧（筒子页），这里放在新坐标 x 更大的那侧=旧坐标左侧
    x_in = int(xs_old[0])
    mask[top_y:bot_y, x_in - gap - 6:x_in - gap] = 1.0
    if paint_top_outer:
        mask[top_y - gap - 6:top_y - gap, :] = 1.0
    if paint_bottom_outer:
        mask[bot_y + gap:bot_y + gap + 6, :] = 1.0
    if decoy_top_offset is not None:
        d = decoy_top_offset
        mask[top_y - d - 6:top_y - d, :] = 1.0
    if text_below_bottom:
        # 下框"外面"还铺着正文——模拟 bottom 内框线根本没落在下版框上的页
        for r in range(bot_y + gap + 18, min(h - 2, bot_y + gap + 170), 18):
            mask[r:r + 13, 160:w - 160] = 1.0
    top = HLine(y_at_right=float(top_y + 2), slope=0.0, kind="top")
    bottom = HLine(y_at_right=float(bot_y - 2), slope=0.0, kind="bottom")
    verticals = [VLine(x_at_top=float((w - 1) - x), slope=0.0) for x in xs_old[::-1]]
    return mask, top, bottom, verticals


def test_detect_outer_borders_measures_gap_on_all_three_sides():
    mask, top, bottom, verts = _outer_page(gap=40)
    r = detect_outer_borders(mask, top, bottom, verts, width=1000, height=1200)
    assert r["v_outer_side"] == "left"           # 纸边侧在新坐标的左边
    # 口径是**外延**（朝外那侧的半高边缘），墨条 6px 厚，所以量出来是
    # gap+6 而不是 gap。抬头框的 outer_y 也是这个口径，不统一就没法比。
    for k in ("v_outer_offset", "top_outer_offset", "bottom_outer_offset"):
        assert abs(abs(r[k]) - (40 + 6)) < 4, (k, r[k])


def test_detect_outer_borders_prior_window_rejects_far_decoy():
    """书口/纸边的痕迹常常比真外框还黑。上下外框只在竖直外框量出来的
    页级间距 ±OUTER_PRIOR_WIN 里找，所以 -70px 处的假线必须被挡住。
    没有这道窗口时 vol01/32 报过 -58、vol01/47 报过 -62，都不是版框。"""
    mask, top, bottom, verts = _outer_page(gap=40, paint_top_outer=False,
                                            decoy_top_offset=70)
    r = detect_outer_borders(mask, top, bottom, verts, width=1000, height=1200)
    assert r["top_outer_offset"] is None or abs(r["top_outer_offset"]) < 60


def test_detect_outer_borders_reports_none_when_outer_not_printed():
    """上下外框在这批书上大量磨没/被扫描裁掉（vol01/141 bottom 窗内峰值墨
    只有 0.048）。宁可报 None 也不要报一个错的数——放低门槛去凑覆盖率
    是量过的负结果（弱档 6 例里 3 例误差超 10px）。"""
    mask, top, bottom, verts = _outer_page(gap=40, paint_bottom_outer=False)
    r = detect_outer_borders(mask, top, bottom, verts, width=1000, height=1200)
    assert r["bottom_outer_offset"] is None
    assert abs(abs(r["top_outer_offset"]) - (40 + 6)) < 4   # 另一边不受连累


def test_detect_outer_borders_rejects_when_ink_continues_beyond():
    """外框条外面必须是纸。vol02/75、vol02/153 的 `bottom` 内框线本身没落在下版框
    上，外框探测就在正文里挑了最黑的一段，画出来的线**直接穿过文字**（用户实审
    点名）。健康页外条之外的行墨是恰好 0.000 一路到 +110px，那两页从不归零、一直
    0.15~0.26——据此拦掉。"""
    mask, top, bottom, verts = _outer_page(gap=40, text_below_bottom=True)
    r = detect_outer_borders(mask, top, bottom, verts, width=1000, height=1200)
    assert r["bottom_outer_offset"] is None
    assert abs(abs(r["top_outer_offset"]) - (40 + 6)) < 4      # 上边不受连累


# ---------------------------------------------------------------- 界行折线

from open_guji_cv.utils.border_geometry import fit_vlines_polyline, gutter_projection


def _bent_page(w=1400, h=2400, n_cols=6, top_y=300, bot_y=2100, bend=22.0):
    """合成页：界行在中段整体往左鼓出 `bend` px（S 形），版框直。"""
    mask = np.zeros((h, w), dtype=np.float64)
    xs_new = np.linspace(200, w - 200, n_cols + 1)
    ky = [top_y, top_y + (bot_y - top_y) / 3, top_y + 2 * (bot_y - top_y) / 3, bot_y]
    for x0 in xs_new:
        for y in range(top_y, bot_y):
            if y < ky[1]:
                t = (y - ky[0]) / (ky[1] - ky[0]); x = x0 + bend * t
            elif y < ky[2]:
                x = x0 + bend
            else:
                t = (y - ky[2]) / (ky[3] - ky[2]); x = x0 + bend * (1 - t)
            xo = (w - 1) - int(round(x))
            mask[y, xo - 2:xo + 3] = 1.0
    mask[top_y:top_y + 5, :] = 1.0
    mask[bot_y - 5:bot_y, :] = 1.0
    top = HLine(y_at_right=float(top_y + 2), slope=0.0, kind="top")
    bottom = HLine(y_at_right=float(bot_y - 2), slope=0.0, kind="bottom")
    # 直线初值：故意给"两端连线"（中段偏 bend 的一半），模拟直线拟合的折中
    verts = [VLine(x_at_top=float(x0 + bend / 2), slope=0.0) for x0 in xs_new]
    return mask, top, bottom, verts, xs_new, ky


def test_straight_page_stays_one_segment():
    mask, top, bottom, verts, xs, ky = _bent_page(bend=0.0)
    verts = [VLine(x_at_top=float(x), slope=0.0) for x in xs]
    out, seg, w80m, w80x = fit_vlines_polyline(mask, top, bottom, verts, 1400, 2400)
    assert seg == 1 and w80m is not None and w80m <= 6
    assert all(v.segments == 1 for v in out)


def test_bent_page_switches_whole_page_to_three_segments_and_tracks_rule():
    """中段鼓出 22px 的 S 形界行：直线下 w80 大，整页切三段后每段都贴回真墨。"""
    mask, top, bottom, verts, xs, ky = _bent_page(bend=22.0)
    out, seg, w80m, w80x = fit_vlines_polyline(mask, top, bottom, verts, 1400, 2400)
    assert seg == 3 and w80m >= 10
    assert all(v.segments == 3 for v in out)          # 整页统一
    for v, x0 in zip(out, xs):
        # 三个折点 + 两端都该在真线上（误差 <= 2px）
        assert abs(v.x_at(ky[0]) - x0) <= 2
        assert abs(v.x_at(ky[1]) - (x0 + 22)) <= 2
        assert abs(v.x_at(ky[2]) - (x0 + 22)) <= 2
        assert abs(v.x_at(ky[3]) - x0) <= 2
        # 换算回来的斜率符号对：第一段向左、第二段平、第三段向右
        assert v.slope > 0 and abs(v.k2) < 0.01 and v.k3 < 0


def test_polyline_x_at_is_continuous_at_knots():
    v = VLine(x_at_top=100.0, slope=0.02, k2=-0.03, k3=0.01, y1=800.0, y2=1600.0)
    for y in (800.0, 1600.0):
        assert abs(v.x_at(y - 1e-6) - v.x_at(y + 1e-6)) < 1e-3
    assert v.segments == 3 and v.knots() == [800.0, 1600.0]


def test_stroke_fragments_do_not_fake_a_bend():
    """vol02/3 型：界行是直的，但断掉的行里混进 <=9px 的笔画碎片。碎片在 y 方向
    是跳的、线是连的——局部一致性闸把它们剔掉，页面必须留在直线（seg=1）。"""
    mask, top, bottom, verts, xs, ky = _bent_page(bend=0.0)
    verts = [VLine(x_at_top=float(x), slope=0.0) for x in xs]
    rng = np.random.default_rng(7)
    # 每条线随机抹掉 1/3 的行，再在这些行的窗口里随机撒 6px 宽的碎片
    for x0 in xs:
        xo = (1400 - 1) - int(round(x0))
        for y in range(300, 2100):
            if rng.random() < 0.33:
                mask[y, xo - 2:xo + 3] = 0.0
                off = int(rng.integers(-30, 31))
                if abs(off) > 6:
                    mask[y, xo + off - 3:xo + off + 3] = 1.0
    out, seg, w80m, w80x = fit_vlines_polyline(mask, top, bottom, verts, 1400, 2400)
    assert seg == 1, (seg, w80m, w80x)
    assert w80m is not None and w80m <= 7
