"""待审原因判定（review/reasons.py）：造格子，核每条规则与先后、判不出给 unknown、写回待审单。"""
import json

from open_guji_cv.review.pending_reason import PendingReason as R
from open_guji_cv.review.reasons import Cell, build_context, classify, reasons_for_pending, stamp


def _cls(cells, lib=None, var=None):
    ctx = build_context(cells, lib_n=lib, are_variants=var)
    return [classify(c, ctx) for c in cells]


def test_unknown_when_no_rule_hits():
    assert _cls([Cell(id="v:1:1:1", char="甲", ref="甲")]) == [R.LIB_UNRECOGNIZED]
    assert _cls([Cell(id="v:1:1:1", char=None, ref=None, doubts=["foo"])], ) == [R.REF_GAP]
    c = Cell(id="v:1:1:1", char="甲", ref="甲")
    ctx = build_context([c])
    # 去掉兜底规则也只会落到 unknown，不会报错
    from open_guji_cv.review import reasons
    saved = reasons.RULES.pop(R.LIB_UNRECOGNIZED)
    try:
        assert classify(c, ctx) is R.UNKNOWN
    finally:
        reasons.RULES[R.LIB_UNRECOGNIZED] = saved


def test_review_states_first():
    c = Cell(id="v:1:1:1", char="已", ref="己", doubts=["occluded"], recheck=True, note="机器改判「□」→「已」，请核")
    assert _cls([c]) == [R.MACHINE_CHANGED]
    c2 = Cell(id="v:1:1:2", char="甲", ref="甲", recheck=True, note="旧裁 山，新票 由")
    assert _cls([c2]) == [R.RECHECK]
    assert _cls([Cell(id="v:1:1:3", char="甲", ref="甲", doubts=["src_code_conflict"])]) == [R.RULING_CONFLICT]


def test_occluded_split_by_ref():
    a = Cell(id="v:1:1:1", char="甲", ref="甲", doubts=["occluded"])
    b = Cell(id="v:1:1:2", char="甲", ref="〓", doubts=["occluded"])
    assert _cls([a, b]) == [R.OCCLUDED_WITH_REF, R.OCCLUDED_NO_REF]


def test_page_and_column_unaligned():
    page = [Cell(id=f"v:2:{i // 20 + 1}:{i % 20 + 1}", char="甲", ref=None) for i in range(10)]
    assert set(_cls(page)) == {R.SEG_PAGE_UNALIGNED}
    col = [Cell(id=f"v:3:4:{i}", char="甲", ref=None) for i in range(5)]
    assert set(_cls(col)) == {R.SEG_COL_UNALIGNED}


def test_hard_pair_before_group():
    c = Cell(id="v:1:1:1", char="日", ref="曰", evidence={"group": {"id": "ry", "solvers": []}})
    assert _cls([c]) == [R.HARD_PAIR]


def test_group_kinds():
    g = lambda **k: Cell(id="v:1:1:1", char="傅", ref="傳", evidence={"group": {"id": "fc", **k}})
    assert _cls([g(solvers=[{"char": None}])]) == [R.GROUP_ABSTAIN]
    assert _cls([g(solvers=[{"char": "傅"}, {"char": "傳"}])]) == [R.GROUP_CONFLICT]
    assert _cls([g(solvers=[{"char": "傅"}], why="ref_dissent")]) == [R.GROUP_REF_DISSENT]
    assert _cls([g(solvers=[{"char": "傅"}], decision="demote")]) == [R.GROUP_DEMOTED]
    assert _cls([g(solvers=[{"char": "傅"}])]) == [R.GROUP_WEAK]


def test_lib_and_ref_rules():
    lib = {"乙": 1, "甲": 50}.get
    lib_n = lambda ch: lib(ch) or 0
    cells = [
        Cell(id="v:1:1:1", char="甲", ref="〓"),
        Cell(id="v:1:1:2", char="甲", ref="丙", doubts=["库里没有这个字"]),
        Cell(id="v:1:1:3", char="甲", ref="甲", doubts=["ctx_garble_shape"]),
        Cell(id="v:1:1:4", char="乙", ref="乙"),
        Cell(id="v:1:1:5", char="甲", ref="乙"),
        Cell(id="v:1:1:6", char="丁", ref="甲", ref_op="replace"),
        Cell(id="v:1:1:7", char="丁", ref="甲"),
        Cell(id="v:1:1:8", char="丁", ref="甲", evidence={"guard": "conflict"}),
    ]
    assert _cls(cells, lib=lib_n) == [R.REF_LACUNA, R.LIB_MISSING, R.GARBLE_GATE, R.LIB_SPARSE_AGREE,
                                      R.LIB_SPARSE_DISSENT, R.REF_REPLACED, R.REF_MISMATCH, R.NEAR_FORM_GUARD]


def test_sparse_needs_lib_counts():
    """没给库样本数就不判「刻例太少」，不猜。"""
    assert _cls([Cell(id="v:1:1:1", char="乙", ref="乙")]) == [R.LIB_UNRECOGNIZED]


def test_variant_pair():
    var = lambda a, b: {a, b} == {"衞", "衛"}
    c = Cell(id="v:1:1:1", char="衞", ref="衛", cands=[["衞", 0.9]])
    assert _cls([c], lib=lambda ch: 50, var=var) == [R.VARIANT_PAIR]


def _page(tmp_path, book, page, chars, align=None, gm=None):
    root = tmp_path / book
    for layer, body in (("seed_admit", {"columns": [{"chars": chars}]}), ("align_ref", align or {"chars": []}),
                        ("glyph_match", gm or {"columns": []})):
        (root / layer).mkdir(parents=True, exist_ok=True)
        (root / layer / f"p{page:04d}.json").write_text(json.dumps({layer: body}), encoding="utf-8")


def test_reasons_for_pending_and_stamp(tmp_path):
    _page(tmp_path, "vol9", 1,
          [{"id": "vol9:1:1:1", "admit": False, "char": "甲", "doubts": ["occluded"], "evidence": {}},
           {"id": "vol9:1:1:2", "admit": True, "char": "乙"}],
          align={"chars": [{"id": "vol9:1:1:1", "align_char": "甲", "align_op": "equal"}]})
    doc = {"cells": [{"cell": "1:1:1", "why": ["occluded"]},
                     {"cell": "7:7:7", "why": [], "recheck": True, "note": "机器改判「□」→「甲」"},
                     {"cell": "8:8:8", "why": []}]}
    res = reasons_for_pending(doc, tmp_path, "vol9", are_variants=lambda a, b: False)
    n = stamp(doc, res)
    got = {c["cell"]: c["pending_reason"] for c in doc["cells"]}
    assert got == {"1:1:1": "occluded_with_ref", "7:7:7": "machine_changed", "8:8:8": "ref_gap"}
    assert sum(n.values()) == 3
    assert all("pending_reason" in c for c in doc["cells"])
