# -*- coding: utf-8 -*-
"""体检 same_cell() 同格判据收紧：与 GlyphMatcher._same_cell_rows /
CnnCandidates._real_index._excluded 同口径——精确坐标（非 v1:）要求格号差 =0，
v1: 侧（idx 坐标、未经形状确认）保留 ±2 容差（2026-09-27，字形库 12 §六；
任务书追加，与 R #61 `0449e98` 同一次收紧的第三处）。"""

from open_guji_cv.clustering.glyph_selfcheck import _same_physical_cell
from open_guji_cv.clustering.match import _cell_parts


def test_precise_adjacent_cells_not_same():
    """两边都是精确格号（非 v1:）时，相邻格（差 1）不再算同一物理格。"""
    a = _cell_parts("vol01:3:4:5")
    b = _cell_parts("vol01:3:4:6")
    assert a[4] and b[4]
    assert not _same_physical_cell(a, b)


def test_precise_identical_slot_is_same():
    a = _cell_parts("v2:vol01:3:4:5")
    b = _cell_parts("vol01:3:4:5")
    assert _same_physical_cell(a, b)


def test_v1_side_keeps_tolerance_diff2():
    """有一边是 v1:（idx 换算、未确认）时，格号差 2 仍保留兜底摘除。"""
    a = _cell_parts("vol01:3:4:5")
    b = _cell_parts("v1:vol01:3:4:2")   # idx=2 → 格号 3，差 2
    assert a[4] and not b[4]
    assert _same_physical_cell(a, b)


def test_v1_side_diff3_not_same():
    """v1: 侧差到 3 就超出容差，不算同格。"""
    a = _cell_parts("vol01:3:4:5")
    b = _cell_parts("v1:vol01:3:4:1")   # idx=1 → 格号 2，差 3
    assert _same_physical_cell(a, b) is False


def test_different_column_never_same():
    a = _cell_parts("vol01:3:4:5")
    b = _cell_parts("vol01:3:5:5")
    assert _same_physical_cell(a, b) is False


def test_unparsable_side_never_same():
    a = _cell_parts("vol01:3:4:5")
    assert _same_physical_cell(a, None) is False
    assert _same_physical_cell(None, None) is False
