# -*- coding: utf-8 -*-
"""steps/decide.py 的读口：`ref_of`／`text_refs`／`coord_refs` 与 seed_admit 原来的 `_align`／`_coord_refs` 同口径。"""
from open_guji_cv.products.kinds.recog import AlignRec, CoordRec, PageAlignRef
from open_guji_cv.utils.gap import GAP_IMAGE
from open_guji_cv.steps import decide, seed_admit as sa

B = "b:1"


def _ref(anchored=True, via="ngram"):
    return PageAlignRef(
        page=1, anchored=anchored, anchor_via=via,
        chars=[AlignRec(id=f"{B}:1:1", col=1, slot=1, align_char="甲", align_op="equal"),
               AlignRec(id=f"{B}:1:2", col=1, slot=2, align_char="乙", align_op="replace")],
        coord=[CoordRec(id=f"{B}:1:2", col=1, slot=2, ref_char="丙"),
               CoordRec(id=f"{B}:1:3", col=1, slot=3, ref_char=""),
               CoordRec(id=f"{B}:1:4", col=1, slot=4, ref_char="က")])


def test_view_merges_text_and_coord():
    v = decide.ref_view(_ref())
    assert v[f"{B}:1:1"] == {"ref": "甲", "via": "text", "op": "equal"}
    assert v[f"{B}:1:2"] == {"ref": "乙", "via": "text", "op": "replace", "coord": "丙"}   # 两路都有：ref 取文本对位
    assert v[f"{B}:1:3"] == {"ref": "", "via": "coord", "op": None, "coord": ""}
    assert v[f"{B}:1:4"]["coord"] == GAP_IMAGE                                              # 缅甸字母占位按缺字看
    assert decide.ref_view(_ref(via="pin"))[f"{B}:1:1"]["via"] == "pin"


def test_unanchored_page_has_coord_only():
    v = decide.ref_view(_ref(anchored=False))
    assert {x["via"] for x in v.values()} == {"coord"}
    assert decide.text_refs(_ref(anchored=False)) == {}
    assert decide.ref_view(None) == {}


def test_seed_admit_wrappers_use_same_readers(monkeypatch):
    ref = _ref()
    monkeypatch.setattr(sa, "_opt", lambda ctx, kind, page: ref)
    assert sa._align(None, 1) == {f"{B}:1:1": ("甲", "equal"), f"{B}:1:2": ("乙", "replace")}
    cache: dict = {}
    got = sa._coord_refs(None, 1, cache)
    assert list(got) == [f"{B}:1:2", f"{B}:1:3", f"{B}:1:4"] and got[f"{B}:1:2"] == "丙" and cache["coord"] is got
