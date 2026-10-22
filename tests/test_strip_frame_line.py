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
    out = strip_frame_line(p, 10, 130, 0, W, line_ys=((116.0, 3.0),))
    assert (out[112:] == 255).all()
    assert (out[20:100, 80:90] == 0).all()


def test_solid_stroke_on_page_line_position_kept():
    """压在全页线位上的字底横是一整笔（列尾「土」），不当淡线剥。"""
    p = _patch()
    p[110:116, 30:150] = 0
    out = strip_frame_line(p, 10, 130, 0, W, line_ys=((113.0, 3.0),))
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
    assert len(offs) == 1 and 27 <= offs[0][0] <= 30 and offs[0][1] == 3


def test_double_frame_with_joining_ink_removed():
    """「乾」：字下隔着白行是一道粗内框，内外两道框之间有竖向连墨，两道一起剥。"""
    p = np.full((H + 20, W), 255, np.uint8)
    p[20:100, 80:90] = 0
    p[108:120, 6:174] = 0          # 内框（离字 8 行白）
    for x in (10, 60, 110, 160):   # 两道框之间的连墨
        p[120:128, x:x + 6] = 0
    p[128:132, 6:174] = 0          # 外框
    out = strip_frame_line(p, 10, 130, 0, W)
    assert (out[106:] == 255).all()
    assert (out[20:100, 80:90] == 0).all()


def test_char_foot_on_inner_frame_with_outer_frame_kept():
    """字脚压在内框上、下面还有外框：内框连着字，不当框剥（只剥外框），字的底横不动。"""
    p = _patch()
    p[96:104, 12:168] = 0          # 满宽底横，紧贴内框
    p[104:107, 6:174] = 0          # 内框
    for x in range(10, 170, 20):   # 两道框之间连墨多（原判据就不剥内框）
        p[107:118, x:x + 8] = 0
    p[118:122, 6:174] = 0
    out = strip_frame_line(p, 10, 130, 0, W)
    assert (out[:104] == p[:104]).all()


def test_thick_solid_bar_removed_even_touching_head_char():
    """「尚」：列首又厚又满的粗版框，贴着字也剥。"""
    p = _patch()
    p[10:34, 4:176] = 0            # 24 行粗框（> FRAME_LINE_THICK 格高），满宽
    p[34:40, 84:88] = 0            # 字头的点贴着框
    out = strip_frame_line(p, 10, 130, 0, W, bottom=False)
    assert (out[:34] == 255).all()
    assert (out[20:100, 80:90][14:] == 0).all()


def test_short_solid_line_matching_page_line_removed():
    """「而」：双边框内框贴着字脚、两头没到窗边（跨度不到 FRAME_LINE_SPAN），位置和厚度都跟全页线位对上就剥。"""
    p = _patch()
    p[100:112, 40:48] = 0          # 字脚压到线上
    p[100:112, 120:128] = 0
    p[112:116, 28:156] = 0         # 4 行实线，0.81 窗宽、两头没到窗边
    assert (strip_frame_line(p, 10, 130, 0, W) == p).all()
    out = strip_frame_line(p, 10, 130, 0, W, line_ys=((113.5, 4.0),))
    assert (out[112:] == 255).all()
    assert (out[20:100, 80:90] == 0).all()
