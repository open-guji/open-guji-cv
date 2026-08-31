"""column_projection 单测：合成图验证射影矫正 + 去噪。"""
import cv2
import numpy as np

from open_guji_cv.utils.border_geometry import VLine
from open_guji_cv.utils.column_projection import denoise_column, warp_column

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
