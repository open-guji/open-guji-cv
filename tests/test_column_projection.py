"""column_projection 单测：合成图验证射影矫正 + 去噪。"""
import cv2
import numpy as np

from open_guji_cv.utils.border_geometry import HLine, VLine
from open_guji_cv.utils.column_projection import (
    column_bounds,
    column_profile,
    column_text_band,
    denoise_column,
    strip_column_rules,
    warp_column,
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
    assert 172 <= right <= 175
    x0 = (180 - 110) // 2
    assert left <= x0 and right >= x0 + 110     # 字身完整落在带内


def test_column_text_band_leaves_rule_free_side_alone():
    """版心侧没有界行（被装订切掉）时，那一侧不该被啃。"""
    img = _column_with_rules()
    img[:, :5] = 255                            # 抹掉左界行
    left, right = column_text_band(img)
    assert left == 0
    assert right < img.shape[1]                  # 右侧界行照常吃掉


def test_column_text_band_never_eats_more_than_max_rule_frac():
    """整列全是墨（退化输入）时，每侧最多啃掉 max_rule_frac，带不会被吃空。
    宁可留残墨也不切字——切掉的字下游补不回来。"""
    img = np.zeros((400, 100), dtype=np.uint8)
    left, right = column_text_band(img, max_rule_frac=0.15)
    assert (left, right) == (15, 85)
    assert left < right


def test_column_text_band_falls_back_when_cap_allows_eating_everything():
    """max_rule_frac >= 0.5 时两侧会啃穿，此时应原样返回整条、而不是空带。"""
    img = np.zeros((400, 100), dtype=np.uint8)
    assert column_text_band(img, max_rule_frac=0.6) == (0, 100)


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
