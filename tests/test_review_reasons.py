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


def test_seg_kind_detail():
    """切坏细分作 seg_defect 的 detail（SJ 第 8 轮，11-04）：单上 seg_kind 优先，其次 evidence；不认的值不带。"""
    from open_guji_cv.review.reasons import detail_of
    ctx = build_context([])
    a = Cell(id="v:1:1:1", char="甲", doubts=["seg_defect"], seg_kind="merged")
    b = Cell(id="v:1:1:2", char="乙", doubts=["seg_defect"], evidence={"seg_kind": "frame_residue"})
    c = Cell(id="v:1:1:3", char="丙", doubts=["seg_defect"], seg_kind="bogus")
    for x in (a, b, c):
        assert classify(x, ctx) is R.SEG_DEFECT
    assert [detail_of(R.SEG_DEFECT, x) for x in (a, b, c)] == ["merged", "frame_residue", ""]


def test_seg_kind_from_pending_list(tmp_path):
    doc = {"cells": [{"cell": "1:1:1", "why": ["seg_defect"], "seg_kind": "clipped"}]}
    res = reasons_for_pending(doc, tmp_path, "vol9", are_variants=lambda a, b: False)
    assert res["1:1:1"] == (R.SEG_DEFECT, "clipped")


def test_jiazhu_uneven_is_seg_defect():
    """史記夹注两行分法不均（doubt 码 jiazhu_uneven，cv#1011）归 seg_defect，细分 jiazhu_uneven。"""
    from open_guji_cv.review.reasons import detail_of
    c = Cell(id="v:1:2:3a", char="甲", ref="甲", doubts=["jiazhu_uneven"])
    assert _cls([c]) == [R.SEG_DEFECT]
    assert detail_of(R.SEG_DEFECT, c) == "jiazhu_uneven"
    c2 = Cell(id="v:1:2:4", char="甲", ref="甲", evidence={"seg_kind": "jiazhu_uneven"}, doubts=["seg_defect"])
    assert detail_of(R.SEG_DEFECT, c2) == "jiazhu_uneven"


def test_lib_missing_detail_split():
    """lib_missing 细分（A23，11-04）：整理本无字／本书借库都没有／借库有本书没有／本书已有，写成「细分:字」。"""
    from open_guji_cv.review.reasons import detail_of, lib_missing_kind
    split = {"以": (0, 40), "松": (0, 0), "人": (12, 30)}
    ctx = build_context([], lib_split=lambda ch: split.get(ch, (0, 0)))
    cells = {"以": Cell(id="v:1:1:1", char="取", ref="以", doubts=["库里没有这个字"]),
             "松": Cell(id="v:1:1:2", char="林", ref="松", doubts=["库里没有这个字"]),
             "人": Cell(id="v:1:1:3", char="入", ref="人", doubts=["库里没有这个字"]),
             "∅": Cell(id="v:1:1:4", char="和", ref=None, doubts=["库里没有这个字"])}
    for c in cells.values():
        assert classify(c, ctx) is R.LIB_MISSING
    assert {k: detail_of(R.LIB_MISSING, c, ctx) for k, c in cells.items()} == {
        "以": "own_zero_borrow_has:以", "松": "all_zero:松", "人": "own_has:人", "∅": "ref_blank:"}
    no_lib = build_context([])
    assert detail_of(R.LIB_MISSING, cells["以"], no_lib) == "以"          # 没给库不分，照旧只写整理本字
    assert detail_of(R.LIB_MISSING, cells["以"]) == "以"
    assert lib_missing_kind(cells["∅"], no_lib) == "ref_blank"


def test_lib_split_counts_own_vs_borrowed(tmp_path):
    import random
    import sqlite3

    import cv2

    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.clustering.synth import degrade, synthetic_glyph
    from open_guji_cv.review.reasons import lib_split_counts

    def png(seed):
        g = degrade(synthetic_glyph(random.Random(700 + seed)), random.Random(seed), wear=0.3)
        return cv2.imencode(".png", 255 - (g * 255).astype("uint8"))[1].tobytes()
    p = tmp_path / "g.db"
    db = GlyphDB(p)
    try:
        for i, (iid, ch) in enumerate([("o:1", "以"), ("b:1", "以"), ("b:2", "以"), ("b:3", "人")]):
            db.admit_instance(iid, ch, png(i), provenance="human", edition_tag="ted", page="1", col=i, idx=1)
        db.conn.commit()
    finally:
        db.close()
    with sqlite3.connect(p) as c:
        c.execute("CREATE TABLE borrowed (instance_id TEXT PRIMARY KEY, store TEXT)")
        c.executemany("INSERT INTO borrowed VALUES (?, 'x')", [("b:1",), ("b:2",), ("b:3",)])
    f = lib_split_counts(p)
    assert f("以") == (1, 2) and f("人") == (0, 1) and f("松") == (0, 0)
    assert lib_split_counts(tmp_path / "none.db") is None
