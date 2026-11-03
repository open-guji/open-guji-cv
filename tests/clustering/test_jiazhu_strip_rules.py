"""夹注格列端剥框线只认贴着版框的线（cell_shrink.jiazhu_strip_rules，写本；SJ r5，2026-11-03）。"""
import numpy as np

from open_guji_cv.clustering.extractor import FRAME_LINE_JZ_REACH, strip_frame_line

CELL_H = 120.0


def _two_rows(line: bool):
    p = np.full((140, 180), 255, np.uint8)
    if line:
        p[0:4, 6:80] = 0              # 版框横线（中缝处断开），贴着版框 y=0
        p[0:4, 100:174] = 0
    p[40:110, 40:50] = 0              # 两个小字
    p[40:110, 130:140] = 0
    p[26:30, 10:84] = 0               # 两行小字的顶横并排，连起来够满宽，离框 26 行
    p[26:30, 96:170] = 0
    return p


def _strip(p, reach):
    return strip_frame_line(p, 10, 130, 0, 180, bottom=False, frame_reach=(0.0, reach * CELL_H))


def test_jz_reach_strips_line_at_frame():
    p = _two_rows(line=True)
    out = _strip(p, FRAME_LINE_JZ_REACH)
    assert (out[:5] == 255).all()
    assert (out[26:110] == p[26:110]).all()


def test_jz_reach_keeps_paired_strokes_off_the_frame():
    p = _two_rows(line=False)
    assert (_strip(p, 0.35) != p).any()            # 写本全书的 0.35：并排顶横被当线剥掉
    assert (_strip(p, FRAME_LINE_JZ_REACH) == p).all()


def test_long_rule_through_ignores_ink_edges_and_spares_radical_beside_line():
    """夹注半格：贯穿的竖线就算落在字缘以内也剥；跟线并成一段的「氵」点不跟着抹。"""
    from open_guji_cv.clustering.extractor import strip_long_rule
    cell = 80
    ink = np.zeros((5 * cell, 120), dtype=bool)
    for k in range(5):
        ink[k * cell + 10:k * cell + 70, 40:100] = True      # 字
    ink[:, 5:9] = True                                        # 贯穿的界行
    ink[2 * cell + 20:2 * cell + 30, 10:16] = True            # 「氵」两点：离线 1px，与线并成一段
    ink[2 * cell + 45:2 * cell + 55, 10:16] = True
    patch = np.where(ink[2 * cell:3 * cell], 0, 255).astype(np.uint8)
    edges = (6.0, 100.0)                                      # 半格小字贴着列缘，字缘量进了线里
    assert (strip_long_rule(patch, ink, 2 * cell, 2 * cell, 3 * cell, ink_edges=edges) == patch).all()
    out = strip_long_rule(patch, ink, 2 * cell, 2 * cell, 3 * cell, ink_edges=edges, through=True)
    assert (out[:, 5:9] == 255).all()
    assert (out[20:30, 10:16] == 0).all() and (out[45:55, 10:16] == 0).all()
    assert (out[10:70, 40:100] == 0).all()


# ── 半格框线（SJ r6，2026-11-03）：内框细线离框约 0.2 格、在两行之间断开 ─────────────
def _half(line_y=None, top_stroke=False):
    p = np.full((140, 80), 255, np.uint8)
    p[50:110, 30:44] = 0                      # 小字
    if line_y is not None:
        p[line_y:line_y + 4, 2:78] = 0        # 框线横贯半格
    if top_stroke:
        p[30:34, 4:76] = 0                    # 小字的长顶横，跟字隔着白
    return p


def test_half_line_on_page_line_position_is_stripped():
    from open_guji_cv.clustering.extractor import strip_jiazhu_half_line
    p = _half(line_y=24)
    out = strip_jiazhu_half_line(p, 0.0, CELL_H, bottom=False, line_ys=((26.0, 4.0),))
    assert (out[:30] == 255).all() and (out[50:110] == p[50:110]).all()
    flip = strip_jiazhu_half_line(p[::-1], 140.0, CELL_H, bottom=True, line_ys=((140 - 26.0, 4.0),))
    assert (flip[::-1][:30] == 255).all()


def test_half_line_needs_page_line_position():
    """并排小字的长顶横离框也这么近：不在全页线位上（或这页没有线位）不剥。"""
    from open_guji_cv.clustering.extractor import strip_jiazhu_half_line
    p = _half(top_stroke=True)
    assert (strip_jiazhu_half_line(p, 0.0, CELL_H, bottom=False) == p).all()
    assert (strip_jiazhu_half_line(p, 0.0, CELL_H, bottom=False, line_ys=((12.0, 4.0),)) == p).all()


def test_half_line_keeps_lone_stroke_char():
    """线下没字（只有一横的「一」）不剥。"""
    from open_guji_cv.clustering.extractor import strip_jiazhu_half_line
    p = np.full((140, 80), 255, np.uint8)
    p[24:28, 2:78] = 0
    assert (strip_jiazhu_half_line(p, 0.0, CELL_H, bottom=False, line_ys=((26.0, 4.0),)) == p).all()


def test_long_rule_through_strips_frame_touching_stroke():
    """外侧竖框跟字的捺脚碰上、连成一段太宽（02:32:1:3a「誕」）：只抹贴外沿的线列。"""
    from open_guji_cv.clustering.extractor import strip_long_rule
    p = np.full((120, 100), 255, np.uint8)
    p[20:100, 4:12] = 0                      # 字的左偏旁（言）
    p[20:100, 20:30] = 0                     # 字的右半
    p[90:94, 20:96] = 0                      # 捺脚一直伸到线上
    strip = np.zeros((400, 100), dtype=bool)
    strip[:, 94:97] = True                   # 竖框贯穿整列
    p[:, 94:97] = 0
    strip[140:220] |= p[20:100] < 128
    out = strip_long_rule(p, strip, 120, 140.0, 240.0, through=True)
    assert (out[:, 94:97] == 255).all()
    assert (out[20:100, 20:30] == 0).all()
