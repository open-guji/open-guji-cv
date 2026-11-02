"""row_segment 书级开关 roster_top_dash：题列顶上断续上版框残渣（史記目錄页 p87 c2 类）。"""
import numpy as np

from open_guji_cv.books.shiji_wyg.roster_segment import _strip_rules
from open_guji_cv.steps.row_segment import RowSegmentParams


def _ink():
    h, w = 2558, 190
    ink = np.zeros((h, w), bool)
    ink[15:21, 37:50] = True       # 上版框残渣：13×6，与首字隔 20 行
    ink[41:164, 40:170] = True     # 首字
    ink[174:393, 40:170] = True
    return ink


def test_default_off_and_not_in_dump():
    assert RowSegmentParams().roster_top_dash is False
    assert "roster_top_dash" not in RowSegmentParams().model_dump()
    assert "roster_top_dash" in RowSegmentParams(roster_top_dash=True).model_dump()


def test_off_leaves_dash():
    ink = _ink()
    assert np.array_equal(_strip_rules(ink), ink)          # 关＝与旧行为逐位同
    assert _strip_rules(ink)[15:21].any()


def test_on_strips_dash_only():
    ink = _ink()
    out = _strip_rules(ink, top_dash=True)
    assert not out[15:21].any()
    assert np.array_equal(out[41:], ink[41:])              # 字不动


def test_on_keeps_char_near_top_and_close_neighbour():
    ink = _ink()
    ink[15:21] = False
    ink[30:36, 90:103] = True      # 紧贴首字的小块（隔 5 行）：不当残渣
    ink[41:164, 40:170] = True
    assert np.array_equal(_strip_rules(ink, top_dash=True), ink)
    ink2 = np.zeros_like(ink)
    ink2[200:300, 40:170] = True   # 首块不在上端 5% 内
    assert np.array_equal(_strip_rules(ink2, top_dash=True), ink2)
