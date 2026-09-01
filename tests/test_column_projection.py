"""column_projection 单测：合成图验证射影矫正 + 去噪。"""
import cv2
import numpy as np

from open_guji_cv.utils.border_geometry import (
    BorderDetectionResult,
    HeadRaiseBorder,
    HLine,
    VLine,
)
from open_guji_cv.utils.column_projection import (
    column_border_trim,
    column_bounds,
    column_profile,
    column_row_profile,
    column_text_band,
    denoise_column,
    page_column_windows,
    strip_column_borders,
    strip_column_rules,
    warp_column,
    warp_page_columns,
)

H, W = 200, 160


def _tilted_column_image(left_x_top, left_x_bot, right_x_top, right_x_bot):
    """画一个原图坐标(左上角原点)下、顶/底端点各自给定的倾斜列（白底黑列）。"""
    img = np.full((H, W), 255, dtype=np.uint8)
    poly = np.array([[left_x_top, 0], [right_x_top, 0],
                      [right_x_bot, H - 1], [left_x_bot, H - 1]], dtype=np.int32)
    cv2.fillPoly(img, [poly], 0)
    return img


def test_warp_column_straightens_tilted_column_into_solid_rectangle():
    """列区域整片是墨（倾斜的黑色条带），矫正之后应该变成一个几乎全黑的
    竖直矩形——如果射影矩阵算错了，矫正区域会漏出白底，均值会明显偏高。"""
    left_top, left_bot = 40, 60    # 左边线：顶端 x=40，底端 x=60（有倾斜）
    right_top, right_bot = 100, 120  # 右边线：顶端 x=100，底端 x=120
    img = _tilted_column_image(left_top, left_bot, right_top, right_bot)

    left = VLine.from_endpoints(left_top, 0, left_bot, H - 1, W)
    right = VLine.from_endpoints(right_top, 0, right_bot, H - 1, W)

    warped = warp_column(img, left, right)
    assert warped.shape[0] == H - 1
    assert abs(warped.shape[1] - 60) <= 2
    assert warped.mean() < 20  # 几乎全黑


def test_warp_column_rejects_degenerate_range():
    left = VLine(x_at_top=10, slope=0.0)
    right = VLine(x_at_top=50, slope=0.0)
    img = np.zeros((H, W), dtype=np.uint8)
    try:
        warp_column(img, left, right, top_y=100, bottom_y=100)
        assert False, "should have raised"
    except ValueError:
        pass


def test_denoise_column_removes_isolated_dot_keeps_stroke():
    img = np.full((80, 60), 255, dtype=np.uint8)
    img[20:60, 25:30] = 0       # 一笔竖画，40x5，面积远大于阈值
    img[5:7, 5:7] = 0            # 孤立小点，2x2=4像素

    out = denoise_column(img, ink_threshold=128, min_blob_area=6)

    assert (out[20:60, 25:30] == 0).all()   # 笔画原样保留
    assert (out[5:7, 5:7] == 255).all()      # 小点被清成背景


# ---- Step2 新增：竖直方向投影 / 文字带边界 / 界行清除 ----

def _column_with_rules(width=180, height=1200, rule_w=5, char_w=110):
    """合成一条矫正后的列：左右各一条贯穿全高的界行，中间是等间隔的字块。"""
    img = np.full((height, width), 255, dtype=np.uint8)
    img[:, :rule_w] = 0                       # 左界行
    img[:, width - rule_w:] = 0               # 右界行
    x0 = (width - char_w) // 2
    for k in range(10):                        # 10 个字块，块间留空
        y0 = 20 + k * 115
        img[y0:y0 + 90, x0:x0 + char_w] = 0
    return img


def test_column_profile_is_ink_fraction_per_x():
    img = _column_with_rules()
    prof = column_profile(img)
    assert prof.shape == (img.shape[1],)
    assert prof[0] == 1.0                      # 界行贯穿全高
    assert prof[img.shape[1] // 2] < 0.85      # 字身有块间空隙，到不了满格
    assert prof[6] == 0.0                       # 界行和字之间的留白


def test_column_text_band_excludes_rules_keeps_chars():
    img = _column_with_rules(width=180, rule_w=5, char_w=110)
    left, right = column_text_band(img)
    assert 5 <= left <= 8                       # 吃掉界行，没吃进留白太多
    assert 172 <= right <= 175                  # 半开区间，右端不含
    x0 = (180 - 110) // 2
    assert left <= x0 and right >= x0 + 110     # 字身完整落在带内


def test_column_text_band_leaves_rule_free_side_alone():
    """版心侧没有界行（被装订切掉）时，那一侧不该被啃。"""
    img = _column_with_rules()
    img[:, :5] = 255                            # 抹掉左界行
    left, right = column_text_band(img)
    assert left == 0
    assert right < img.shape[1]                  # 右侧界行照常吃掉


def test_column_text_band_leaves_a_solid_ink_column_untouched():
    """整列全是墨（退化输入）：窗口里没有谷，最低点就是边缘那一格，
    扫到它立刻停 —— 一个像素也不啃，更不会返回空带。"""
    img = np.zeros((400, 100), dtype=np.uint8)
    assert column_text_band(img) == (0, 100)


def test_column_text_band_stops_at_a_low_plateau_instead_of_eating_through_it():
    """界行衰减到一个不归零的低平台（vol01/33 c5 右侧那种贯穿全高的淡竖痕）时，
    平台本身就是窗口最低点，扫到它就该停，不能一路啃到上限。"""
    img = np.full((1000, 120), 255, dtype=np.uint8)
    img[:, :4] = 0                              # 界行本体
    img[:10, 4:9] = 0                            # 衰减尾
    img[:12, 9:40] = 0                           # 贯穿不了全高、但压着的淡竖痕(1.2%)
    img[200:900, 45:100] = 0                     # 字身
    left, _ = column_text_band(img)
    assert 4 <= left <= 9                        # 停在界行尾，没吃进 9~40 那片淡痕


def test_strip_column_rules_whitens_edges_keeps_shape_and_chars():
    img = _column_with_rules()
    out = strip_column_rules(img)
    assert out.shape == img.shape               # 抹白不裁切，坐标系不漂
    prof = column_profile(out)
    assert prof[0] == 0.0 and prof[-1] == 0.0
    x0 = (180 - 110) // 2
    assert (out[20:110, x0:x0 + 110] == 0).all()  # 首字原样保留


def test_column_bounds_uses_page_right_anchor_and_head_raise():
    top = HLine(y_at_right=500.0, slope=-0.03, kind="top")
    bottom = HLine(y_at_right=2900.0, slope=-0.005, kind="bottom")
    assert column_bounds(top, bottom) == (500.0, 2900.0)      # 一律取 x=0 锚点
    assert column_bounds(top, bottom, head_raise_inner_y=330.0) == (330.0, 2900.0)


# ---- Step2 新增：上下版框残墨（水平投影三档 a/b/c）----

def _column_with_top_border(border_h=0, gap=12, glued=False, height=600, width=180):
    """合成一条已去掉侧界行的列：顶部可选一条版框线，之后留间隙或直接接上字。"""
    img = np.full((height, width), 255, dtype=np.uint8)
    if border_h:
        img[:border_h, :] = 0                    # 版框：贯穿整宽
    y0 = border_h if glued else border_h + gap   # glued=版框和首字之间没间隙
    for k in range(4):                            # 几个字块
        top = y0 + k * 120
        img[top:top + 95, 35:145] = 0
    return img


def test_column_row_profile_is_ink_fraction_per_y():
    img = _column_with_top_border(border_h=4)
    prof = column_row_profile(img)
    assert prof.shape == (img.shape[0],)
    assert prof[0] == 1.0            # 版框贯穿整宽
    assert prof[6] == 0.0             # 间隙里没墨


def test_column_row_profile_respects_text_band():
    """界行不排除掉，每一行都有底噪，"归不归零"这个判据就废了。"""
    img = _column_with_top_border(border_h=4)
    img[:, :5] = 0                    # 补一条没清掉的左界行
    assert column_row_profile(img)[10] > 0            # 整幅算：间隙(4~15行)里也有墨
    assert column_row_profile(img, band=(6, 180))[10] == 0   # 带内算：干净


def test_column_border_trim_case_a_removes_whole_border_run():
    img = _column_with_top_border(border_h=5, gap=14)
    (top_px, top_case), (bot_px, bot_case) = column_border_trim(img)
    assert (top_case, top_px) == ("a", 5)
    assert (bot_case, bot_px) == ("c", 0)   # 底部本来就没墨


def test_column_border_trim_case_b_only_takes_glue_px():
    """版框跟首字粘连、看不到间隙时，只削 glue_px，不敢整段切。"""
    img = _column_with_top_border(border_h=5, glued=True)
    (top_px, top_case), _ = column_border_trim(img, glue_px=3)
    assert (top_case, top_px) == ("b", 3)


def test_column_border_trim_case_c_leaves_clean_edge_alone():
    img = _column_with_top_border(border_h=0, gap=20)
    (top_px, top_case), _ = column_border_trim(img)
    assert (top_case, top_px) == ("c", 0)


def test_strip_column_borders_whitens_only_the_border_rows():
    img = _column_with_top_border(border_h=5, gap=14)
    out = strip_column_borders(img)
    assert out.shape == img.shape
    assert (out[:5] == 255).all()                    # 版框抹掉
    assert (out[19:114, 35:145] == 0).all()          # 首字原样保留


def _column_with_inset_border(blank=12, border_h=4, gap=10, height=600, width=180):
    """版框"内缩"：边缘先一段空白，往里才是版框线，再往里才是字。
    column_bounds 取页面右端 x=0 锚点、锚点越过该列真实版框时就长这样。"""
    img = np.full((height, width), 255, dtype=np.uint8)
    img[blank:blank + border_h, :] = 0
    y0 = blank + border_h + gap
    for k in range(4):
        img[y0 + k * 120:y0 + k * 120 + 95, 35:145] = 0
    return img


def test_column_border_trim_case_d_reaches_an_inset_border():
    """只看"边缘有没有墨"会把内缩版框整条漏掉（32列金标里下端有8条是这种）。"""
    img = _column_with_inset_border(blank=12, border_h=4)
    (top_px, top_case), _ = column_border_trim(img)
    assert (top_case, top_px) == ("d", 16)      # 空白 + 横线一起削


def test_column_border_trim_does_not_mistake_the_first_char_for_a_border():
    """边缘空白之后直接是首字（厚 95 行、顶边是细的）时，什么都不该削。"""
    img = _column_with_inset_border(blank=12, border_h=0, gap=0)
    (top_px, top_case), _ = column_border_trim(img)
    assert (top_case, top_px) == ("c", 0)


def test_column_border_trim_row_coverage_alone_would_have_failed():
    """负结果护栏：字身里带满宽长横画的那一行，行墨占比跟版框线一样高——
    只用"墨占比高"判会把它当版框切掉。厚度判据必须扛住这一条。"""
    img = _column_with_inset_border(blank=12, border_h=0, gap=0)
    img[40:52, 5:175] = 0                        # 首字里一道贯穿全宽的长横
    assert column_row_profile(img)[45] > 0.9     # 这一行确实"满宽"
    (top_px, top_case), _ = column_border_trim(img)
    assert (top_case, top_px) == ("c", 0)        # 仍然不动


# --- 逐列矫正窗口 -------------------------------------------------------

def _result_with_tilted_top(n_cols=9, w=1000, h=800, top_slope=0.02, head_raise=()):
    """版框上边是斜的（slope=0.02 → 整页宽度上落差 20px），用来测"页级锚点
    不能代替逐列取值"。"""
    xs = np.linspace(80, w - 80, n_cols + 1)
    verticals = [VLine(x_at_top=float(x), slope=0.0) for x in sorted(xs)]
    return BorderDetectionResult(
        width=w, height=h,
        top=HLine(y_at_right=200.0, slope=top_slope, kind="top"),
        bottom=HLine(y_at_right=700.0, slope=top_slope, kind="bottom"),
        verticals=verticals, head_raise=list(head_raise))


def test_page_column_windows_tracks_tilted_border_per_column():
    """版框斜着走，每一列的 top_y 必须跟着走——这正是页级标量做不到的：
    旧做法整页共用 top.y_at(0)，实测 14 页 126 列里最大偏 54.4px。"""
    res = _result_with_tilted_top()
    wins = page_column_windows(res)
    assert len(wins) == 9
    page_anchor = res.top.y_at(0.0)
    for wnd in wins:
        assert abs(wnd.top_y - wnd.border_top_y) < 1e-6      # 普通列贴着版框
        assert abs(wnd.border_top_in_column) < 1e-6          # 版框正好在列图第 0 行
    # 越靠左(col 越大)离页级锚点越远，且单调
    offs = [w_.top_y - page_anchor for w_ in wins]
    assert offs == sorted(offs, reverse=True) or offs == sorted(offs)
    assert abs(offs[-1]) > abs(offs[0]) + 5


def test_page_column_windows_extends_above_border_for_raised_column():
    """抬头列必须上探到抬头框的内边框——否则列图裁在主版框上，抬头字整段
    在版框以上，直接没了（14 页实测 15 个抬头列各被切掉 106~200px）。"""
    box = HeadRaiseBorder(col=3, inner_y=120.0, outer_y=80.0)
    res = _result_with_tilted_top(head_raise=[box])
    wins = {w_.col: w_ for w_ in page_column_windows(res)}
    raised = wins[3]
    assert raised.raised is True
    assert raised.top_y == 120.0
    # 主版框在列图坐标里落在正数位置，Step 3 的 border_top 要用它
    assert raised.border_top_in_column > 80
    assert wins[2].raised is False and abs(wins[2].border_top_in_column) < 1e-6


def test_page_column_windows_never_starts_below_the_border():
    """上界永远不越过版框往下——越过就等于主动切掉正文顶端。"""
    res = _result_with_tilted_top()
    for wnd in page_column_windows(res, body_pad=-50.0):
        assert wnd.top_y <= wnd.border_top_y + 1e-9


def test_warp_page_columns_returns_one_image_per_column():
    res = _result_with_tilted_top()
    gray = np.full((res.height, res.width), 255, dtype=np.uint8)
    out = warp_page_columns(gray, res)
    assert len(out) == 9
    for wnd, img in out:
        assert img.shape[0] == int(round(wnd.bottom_y - wnd.top_y))
        assert img.shape[1] > 0
