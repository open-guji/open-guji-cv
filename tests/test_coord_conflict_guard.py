# -*- coding: utf-8 -*-
"""A23 2026-10-23 coord_conflict_guard：align_ref 全记坐标与现役 equal 字打架的格。自造数据。"""
from __future__ import annotations

from types import SimpleNamespace

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.products.kinds.recog import PageAlignRef
from open_guji_cv.steps.align_ref import _coord_conflict, _coord_conflict_ids
from open_guji_cv.steps.seed_admit import SeedAdmitParams


def _lg(ch, op="equal", run=9):
    return SimpleNamespace(align_char=ch, align_op=op, ref_run=run)


def test_conflict_ids_collects_all_cells():
    # vol14 60:1:5：坐标 拱 / 现役 撰 equal；同列另一格也冲突，要一并记下
    recs = [("v:60:1:4", 4, None, "高", 0), ("v:60:1:5", 5, None, "拱", 0), ("v:60:1:6", 6, None, "撰", 0),
            ("v:60:1:7", 7, None, "拱", 0)]
    legacy = {"v:60:1:4": _lg("高"), "v:60:1:5": _lg("撰"), "v:60:1:6": _lg("撰"), "v:60:1:7": _lg("揆")}
    assert _coord_conflict_ids(recs, legacy) == ["v:60:1:5", "v:60:1:7"]
    assert "v:60:1:5" in _coord_conflict(recs, legacy, {})            # 第一格仍由原因串报


def test_conflict_ids_skips_blank_replace_and_missing():
    recs = [("a", 1, None, "", 0), ("b", 2, None, "甲", 0), ("c", 3, None, "乙", 0)]
    legacy = {"a": _lg("丙"), "b": _lg("丁", "replace")}              # 坐标空、现役 replace、无现役：都不计
    assert _coord_conflict_ids(recs, legacy) == []


def test_no_switch_param():
    assert "coord_conflict_guard" not in SeedAdmitParams.model_fields      # 常开，无开关


def test_page_align_ref_field_default():
    assert PageAlignRef.model_fields["coord_conflict_ids"].default_factory() == []


def _col(n, bad, bad_run, bad_ch="有", bad_lg="本"):
    """n 格一列，第 bad 格坐标字 bad_ch / 现役 equal bad_lg（段长 bad_run），其余全同。"""
    chars = "天地玄黄宇宙洪荒日月盈昃辰宿列张寒来暑往"
    recs, legacy = [], {}
    for k in range(n):
        i = f"v:50:7:{k + 1}"
        ch = bad_ch if k == bad else chars[k]
        recs.append((i, k + 1, None, ch, 0))
        legacy[i] = _lg(bad_lg if k == bad else chars[k], run=bad_run if k == bad else 9)
    return recs, legacy


def test_isolated_weak_conflict_keeps_column():
    # vol15 p50 列 7：现役 equal 段长 1 的孤立一格不合，其余全同 → 不退回，冲突格仍记 ids
    recs, legacy = _col(14, 10, 1)
    assert _coord_conflict(recs, legacy, {}) == ""
    assert _coord_conflict_ids(recs, legacy) == ["v:50:7:11"]


def test_long_run_conflict_still_drops():
    recs, legacy = _col(14, 10, 5)
    assert "与现役对位冲突" in _coord_conflict(recs, legacy, {})


def test_two_weak_conflicts_drop():
    recs, legacy = _col(14, 10, 1)
    legacy["v:50:7:3"] = _lg("X", run=1)
    assert "与现役对位冲突" in _coord_conflict(recs, legacy, {})


def test_weak_conflict_with_few_agreeing_drops():
    recs, legacy = _col(14, 10, 1)
    for k in range(1, 11):                       # 现役大多缺席：同意的 equal 格不足
        if k != 11:
            legacy.pop(f"v:50:7:{k}", None)
    assert "与现役对位冲突" in _coord_conflict(recs, legacy, {})


def test_shift_like_weak_conflict_drops():
    # 现役字恰是邻格的坐标字 → 整列错位的特征，退回
    recs, legacy = _col(14, 10, 1, bad_ch="有", bad_lg="宿")
    recs[9] = (recs[9][0], 10, None, "有", 0)
    legacy["v:50:7:11"] = _lg(recs[9][3], run=1)   # 现役字 == 前一格坐标字
    assert "与现役对位冲突" in _coord_conflict(recs, legacy, {})


def test_blank_coord_conflict_drops():
    recs, legacy = _col(14, 10, 1, bad_ch="")
    assert "与现役对位冲突" in _coord_conflict(recs, legacy, {})
