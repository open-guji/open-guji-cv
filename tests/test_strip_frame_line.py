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


def _dashed(p, y0, y1, x0=25, x1=145, on=3, off=8):
    for x in range(x0, x1, on + off):
        p[y0:y1, x:x + on] = 0


def test_faint_dashed_line_needs_page_line_position():
    """淡虚线（覆盖不到 FRAME_LINE_COV、两头缺点）：单格认不出，给了全页线位就剥。"""
    p = _patch()
    _dashed(p, 115, 118)
    assert (strip_frame_line(p, 10, 130, 0, W) == p).all()
    out = strip_frame_line(p, 10, 130, 0, W, line_ys=(116.0,))
    assert (out[112:] == 255).all()
    assert (out[20:100, 80:90] == 0).all()


def test_solid_stroke_on_page_line_position_kept():
    """压在全页线位上的字底横是一整笔（列尾「土」），不当淡线剥。"""
    p = _patch()
    p[110:116, 30:150] = 0
    out = strip_frame_line(p, 10, 130, 0, W, line_ys=(113.0,))
    assert (out == p).all()


def test_page_frame_line_offsets_consensus():
    from open_guji_cv.clustering.extractor import page_frame_line_offsets
    cols = []
    for k in range(5):
        img = np.full((400, 180), 255, np.uint8)
        img[370 - (k % 2):373 - (k % 2), 5:175] = 0     # 离版框 400 约 28px，各列 ±1
        if k == 0:
            img[300:304, 5:175] = 0                      # 只有一列有的线：不成线位
        cols.append((img, 0.0, 180.0, 400.0))
    offs = page_frame_line_offsets(cols, cell_h=120.0, bottom=True)
    assert len(offs) == 1 and 27 <= offs[0] <= 30
