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
    RAISE_PAD,
    denoise_column,
    page_column_windows,
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
    """抬头列必须上探到抬头框外延——否则列图裁在主版框上，抬头字整段在版框
    以上，直接没了（14 页实测 15 个抬头列各被切掉 140~187px）。"""
    box = HeadRaiseBorder(col=3, inner_y=120.0, outer_y=80.0)
    res = _result_with_tilted_top(head_raise=[box])
    wins = {w_.col: w_ for w_ in page_column_windows(res)}
    raised = wins[3]
    assert raised.raised is True
    assert raised.top_y == 80.0 - RAISE_PAD
    # 主版框在列图坐标里落在正数位置，Step 3 的 border_top 要用它
    assert raised.border_top_in_column > 100
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
