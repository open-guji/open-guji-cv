"""extractor.strip_long_rule：图块最外侧落在本列字缘以外、上下贯穿多格（或在列端连到格外沿）的竖线抹白。"""

import numpy as np

from open_guji_cv.clustering.extractor import column_ink_edges, strip_long_rule

CELL = 80
W = 120


def _strip(n_cells: int = 5) -> np.ndarray:
    """n_cells 格的列条带（墨=True）：每格中间一个 60px 宽的方块字。"""
    ink = np.zeros((n_cells * CELL, W), dtype=bool)
    for k in range(n_cells):
        ink[k * CELL + 10:k * CELL + 70, 35:95] = True
    return ink


def _patch(ink: np.ndarray, k: int) -> np.ndarray:
    return np.where(ink[k * CELL:(k + 1) * CELL], 0, 255).astype(np.uint8)


def _rows(n: int):
    return [(k * CELL, (k + 1) * CELL) for k in range(n)]


def test_column_ink_edges_ignore_thin_edge_span():
    ink = _strip()
    ink[:, 5:10] = True                       # 整列贯穿的框线不定字缘
    assert column_ink_edges(ink, _rows(5)) == (35.0, 95.0)


def test_long_rule_through_column_is_stripped():
    ink = _strip()
    ink[:, 5:10] = True
    edges = column_ink_edges(ink, _rows(5))
    out = strip_long_rule(_patch(ink, 2), ink, 2 * CELL, 2 * CELL, 3 * CELL, ink_edges=edges)
    assert (out[:, 5:10] == 255).all()
    assert (out[10:70, 35:95] == 0).all()     # 字不动


def test_char_edge_stroke_inside_edges_is_kept():
    """「則」的刂：竖笔在字缘以内，跟上下格的竖笔连成长线也不剥。"""
    ink = _strip()
    ink[2 * CELL:3 * CELL, 35:95] = False
    ink[2 * CELL + 10:2 * CELL + 70, 35:75] = True
    ink[:, 85:92] = True                      # 本格右边的竖笔跟上下格的字连成一条
    edges = column_ink_edges(ink, _rows(5))
    patch = _patch(ink, 2)
    assert strip_long_rule(patch, ink, 2 * CELL, 2 * CELL, 3 * CELL, ink_edges=edges) is patch


def test_corner_line_at_column_tail():
    """双边框内框在列尾拐进来：只在末格里，往下连到格外沿。"""
    ink = _strip()
    ink[4 * CELL + 20:5 * CELL, 5:10] = True
    edges = column_ink_edges(ink, _rows(5))
    patch = _patch(ink, 4)
    out = strip_long_rule(patch, ink, 4 * CELL, 4 * CELL, 5 * CELL, tail=True, ink_edges=edges)
    assert (out[:, 5:10] == 255).all()
    # 不是列端格就不按拐角线剥
    assert strip_long_rule(patch, ink, 4 * CELL, 4 * CELL, 5 * CELL, ink_edges=edges) is patch


def test_short_edge_mark_not_reaching_cell_edge_is_kept():
    ink = _strip()
    ink[4 * CELL + 20:4 * CELL + 60, 5:10] = True     # 没连到格外沿
    edges = column_ink_edges(ink, _rows(5))
    patch = _patch(ink, 4)
    assert strip_long_rule(patch, ink, 4 * CELL, 4 * CELL, 5 * CELL, tail=True, ink_edges=edges) is patch


def test_head_corner_line_starting_below_frame_needs_grow():
    """全唐文第 1 列外侧竖框在上框下面断开约 0.08 格高才起：缺省不认，grow（书级开关）认。"""
    ink = _strip()
    ink[8:CELL, 5:10] = True                       # 列首格：离格外沿 8 行（0.1 格高）起
    edges = column_ink_edges(ink, _rows(5))
    patch = _patch(ink, 0)
    assert strip_long_rule(patch, ink, 0, 0, CELL, head=True, ink_edges=edges) is patch
    out = strip_long_rule(patch, ink, 0, 0, CELL, head=True, ink_edges=edges, grow=True)
    assert (out[:, 5:10] == 255).all()
    assert (out[10:70, 35:95] == 0).all()


def test_single_char_column_dao_kept_with_outer_only():
    """单字成列的「制」（全唐文 009:33:7:5，R038）：字缘就是这个字，刂 落在字缘外、列首又是列尾、长钩连到格底。
    缺省当拐角框线抹掉；outer_only（cell_shrink.long_rule_outer_only）只认贴列窗外沿的一段，刂 在列中间偏右，留着。"""
    ink = np.zeros((CELL, W), dtype=bool)
    ink[10:70, 20:60] = True                       # 左半「⿰」字身
    ink[8:CELL - 2, 72:78] = True                  # 刂 的长竖钩，连到格底
    edges = column_ink_edges(ink, _rows(1))
    patch = _patch(ink, 0)
    out = strip_long_rule(patch, ink, 0, 0, CELL, tail=True, head=True, ink_edges=edges)
    assert (out[:, 72:78] == 255).all()            # 缺省：旧行为，刂 被抹
    assert strip_long_rule(patch, ink, 0, 0, CELL, tail=True, head=True, ink_edges=edges, outer_only=True) is patch


def test_outer_only_still_strips_rule_at_window_edge():
    ink = _strip()
    ink[4 * CELL + 20:5 * CELL, 5:10] = True
    edges = column_ink_edges(ink, _rows(5))
    out = strip_long_rule(_patch(ink, 4), ink, 4 * CELL, 4 * CELL, 5 * CELL, tail=True, ink_edges=edges, outer_only=True)
    assert (out[:, 5:10] == 255).all()
