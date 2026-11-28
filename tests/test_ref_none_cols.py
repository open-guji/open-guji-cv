"""列级无参照（reference_profile 的 kind: none 段带 cols，CV0 2026-11-28，脉经第 2 册缺文小注）。"""
import pytest

from open_guji_cv.core.ref_profile import load_reference_profile
from open_guji_cv.products.kinds.recog import AlignRec, CoordRec, PageAlignRef
from open_guji_cv.steps.align_ref import _strip_none_cols

REFS = [{"file": "a.txt", "form": "text"}]


def _prof():
    return load_reference_profile({"default": "text", "segments": [
        {"pages": [18, 19, 24, 25], "kind": "text", "note": "维基补文"},
        {"pages": [18], "kind": "none", "cols": ["8-11"]},
        {"pages": [25], "kind": "none", "cols": [1, 4]},
        {"pages": [5], "kind": "none"}]}, REFS)


def test_none_cols_read_and_token():
    prof = _prof()
    assert prof.none_cols(18) == frozenset({8, 9, 10, 11})
    assert prof.none_cols(25) == frozenset({1, 4})
    assert prof.none_cols(19) == frozenset() and prof.none_cols(5) == frozenset()
    assert prof.kind_of(18) == "text"                         # 页形态照旧
    assert prof.page_token(18) == "text:0|nc:8,9,10,11"
    assert prof.page_token(19) == "text:0"                    # 没列级段的页指纹不变


def test_column_default_page_gets_token_only_with_cols():
    prof = load_reference_profile({"segments": [{"pages": [3], "kind": "none", "cols": [2]}]}, [{"file": "a"}])
    assert prof.page_token(4) is None and prof.page_token(3) == "column:0|nc:2"


def test_cols_validation():
    with pytest.raises(ValueError, match="kind: none"):
        load_reference_profile({"segments": [{"pages": [1], "kind": "text", "cols": [2]}]}, REFS)
    with pytest.raises(ValueError, match="从 1 起"):
        load_reference_profile({"segments": [{"pages": [1], "kind": "none", "cols": [0]}]}, REFS)


def test_strip_none_cols():
    ar = PageAlignRef(page=18, anchored=True,
                      chars=[AlignRec(id="b:18:7:1", col=7, slot=1, align_char="甲", align_op="equal"),
                             AlignRec(id="b:18:8:1", col=8, slot=1, align_char="乙", align_op="equal")],
                      coord=[CoordRec(id="b:18:9:2", col=9, slot=2, ref_char="丙")], coord_cols=[7, 9],
                      ref_hint={"b:18:10:1": "丁", "b:18:3:1": "戊"})
    _strip_none_cols(ar, frozenset({8, 9, 10, 11}))
    assert [c.col for c in ar.chars] == [7] and ar.coord == [] and ar.coord_cols == [7]
    assert ar.ref_hint == {"b:18:3:1": "戊"} and ar.none_cols == [8, 9, 10, 11]
    assert ar.model_dump()["none_cols"] == [8, 9, 10, 11]
    assert "none_cols" not in PageAlignRef(page=1).model_dump()
