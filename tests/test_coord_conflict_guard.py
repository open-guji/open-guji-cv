# -*- coding: utf-8 -*-
"""A23 2026-10-23 coord_conflict_guard：align_ref 全记坐标与现役 equal 字打架的格。自造数据。"""
from __future__ import annotations

from types import SimpleNamespace

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.products.kinds.recog import PageAlignRef
from open_guji_cv.steps.align_ref import _coord_conflict, _coord_conflict_ids
from open_guji_cv.steps.seed_admit import SeedAdmitParams


def _lg(ch, op="equal"):
    return SimpleNamespace(align_char=ch, align_op=op)


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
