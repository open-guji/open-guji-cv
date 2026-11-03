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
