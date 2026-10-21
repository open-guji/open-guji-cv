"""列端版框细线（extractor.strip_frame_line）：列尾格里横贯窗口的虚线抹掉，字的底横、只有一横的「一」不动。"""
import numpy as np

from open_guji_cv.clustering.extractor import strip_frame_line

W, H = 180, 140      # 图块：内容窗口 [0, 180)，格界 [10, 130)


def _patch():
    p = np.full((H, W), 255, np.uint8)
    p[20:100, 80:90] = 0          # 字：一竖
    p[60:66, 40:130] = 0          # 一横（0.5 窗宽）
    return p


def test_dashed_line_below_char_is_removed():
    p = _patch()
    for x in range(8, 172, 12):   # 虚线框：每 12px 墨 8px，跨满窗口
        p[110:114, x:x + 8] = 0
    out = strip_frame_line(p, 10, 130, 0, W)
    assert (out[105:] == 255).all()
    assert (out[20:100, 80:90] == 0).all()


def test_char_bottom_stroke_kept():
    p = _patch()
    p[96:102, 45:135] = 0          # 底横 0.5 窗宽：不是框
    out = strip_frame_line(p, 10, 130, 0, W)
    assert (out == p).all()


def test_lone_bar_without_char_above_kept():
    p = np.full((H, W), 255, np.uint8)
    p[110:114, 5:175] = 0          # 线内侧没墨：不剥（交给渣格闸）
    out = strip_frame_line(p, 10, 130, 0, W)
    assert (out == p).all()


def test_wide_bottom_stroke_with_feet_kept_frame_below_removed():
    """「其」「兵」：满宽底横下面还有两点，底横是字的；再往下那条才是框。"""
    p = _patch()
    p[88:94, 12:168] = 0           # 满宽底横
    p[96:110, 40:62] = 0           # 两点
    p[96:110, 118:140] = 0
    p[120:123, 8:172] = 0          # 框线
    out = strip_frame_line(p, 10, 130, 0, W)
    assert (out[:118] == p[:118]).all()
    assert (out[118:] == 255).all()


def test_top_line_for_head_cell():
    p = _patch()
    p[14:18, 6:174] = 0
    out = strip_frame_line(p, 10, 130, 0, W, bottom=False)
    assert (out[:18] == 255).all()
    assert (out[20:100, 80:90] == 0).all()


def test_full_width_stroke_deep_inside_cell_kept():
    """离格外沿超过 FRAME_LINE_ZONE 的满宽横是字的（列首「詩」「周」的上横）。"""
    p = _patch()
    p[70:74, 6:174] = 0            # 离下沿 56px = 0.47 格
    out = strip_frame_line(p, 10, 130, 0, W)
    assert (out == p).all()
