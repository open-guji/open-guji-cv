# -*- coding: utf-8 -*-
"""`row_segment.layout_raise_box` 的抬头框判真（`_raise_box_real`）与表重编（`_reraise`）。数据现造。"""
from __future__ import annotations

from types import SimpleNamespace

from open_guji_cv.steps.row_segment import _raise_box_real, _reraise


def _wins(tops: list[tuple[int, float, bool]]):
    cols = [SimpleNamespace(col=c, top_y=t, raised=r) for c, t, r in tops]
    return SimpleNamespace(columns=cols, column=lambda k: next((x for x in cols if x.col == k), None))


def test_raise_box_above_unraised_columns_is_real():
    """殿本 vol45 p18 的实形：不抬头列的列窗上沿约 172，抬头列 62，高出一格多 → 真抬头。"""
    w = _wins([(1, 174, False), (2, 174, False), (3, 157, False), (4, 62, True), (5, 62, True), (6, 172, False)])
    assert _raise_box_real(w, 4, 75.0)
    assert not _raise_box_real(w, 3, 75.0)          # 不抬头的列
    assert not _raise_box_real(w, 9, 75.0)          # 没有这一列


def test_raise_box_on_misread_frame_is_not_real():
    """上版框没认准：每列都带「抬头框」（vol56 p43），或不带框的列上沿和框一样高（vol73 p73）→ 不算。"""
    assert not _raise_box_real(_wins([(c, 62.0 + c, True) for c in range(1, 10)]), 3, 78.0)
    w = _wins([(c, 54.0, True) for c in (1, 2, 3, 4, 5, 7, 8, 9)] + [(6, 66.0, False)])
    assert not _raise_box_real(w, 3, 78.0)


def test_reraise_moves_table_to_box_level():
    """表记不抬头、首字在 1 号格；按闸重编到抬一格：首字到 -1，其余整体前移一格。"""
    lay = {"slots": [1, 2, 3, 21], "notes": [21], "half": [], "raised": 0}
    rr = _reraise(lay, 1)
    assert rr["raised"] == 1 and rr["slots"] == [-1, 1, 2, 20] and rr["notes"] == [20]
