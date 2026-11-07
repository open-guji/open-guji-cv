# -*- coding: utf-8 -*-
"""S02 整列对不上统一放行（A22 2026-11-06，Sheldon 定）：

- 逐列本全角「？」（录不出的字）按 〓 占一个字位（vol20 p133 列 5 原先少一位、整列错格退回）；
- `coord_blank_ink`：整理本一行中间的空格位上有墨（vol19 满文字母）时不要求格连续、按格位配；
  「空格位上库认出了字」与空格位上现役孤立单字对上只记格、不退列（同列其余大多一致才行）；
- seed_admit `blank_ink_nonchar`：空格位上库认不出的格判非字放行，库有把握的留审。
"""
from __future__ import annotations

from types import SimpleNamespace

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.products.kinds.recog import AlignRec
from open_guji_cv.steps import align_ref_coord as C
from open_guji_cv.steps.align_ref import AlignRefParams, _coord_conflict
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _blank_ink_pass


def _cu(slot, g, ch="", kind="c"):
    if kind == "c":
        return C.CellUnit("c", slot, g, {"": f"id{slot}"}, {"": ch})
    return C.CellUnit("n", slot, g, {"a": f"id{slot}a"}, {"a": ch})


def test_fullwidth_question_mark_takes_a_slot_as_lacuna():
    (ln,) = C.parse_lines("#@ x\n　卉斤？厼也")
    assert [(p, u.a) for p, u in ln.text_units()] == [(1, "卉"), (2, "斤"), (3, "〓"), (4, "厼"), (5, "也")]
    (no_grid,) = C.parse_lines("甲？乙")
    assert [u.a for u in no_grid.units] == ["甲", "〓", "乙"]


# vol19 p155 列 8 的样子：「之　<安|>　<恩|>二字以配」，满文字母在空格位上
LINE = "#@ x\n　　之　<安|>　<恩|>二字以配"


def _manchu_units():
    us = [_cu(3, 3.3, "之"), _cu(4, 4.3, "五"), _cu(5, 5.3, "安", "n"), _cu(6, 6.3, "駐"), _cu(7, 7.3, "恩", "n")]
    return us + [_cu(8 + i, 8.3 + i, ch) for i, ch in enumerate("二字以配")]


def test_gap_column_maps_cells_around_ink_in_blank_slots():
    (ln,) = C.parse_lines(LINE)
    units = _manchu_units()
    assert not C.coord_column(units, ln).ok                       # 原配法：满文格夹在中间，整列退回
    r = C.coord_column(units, ln, gap=True)
    assert r.ok and r.note == "空格位夹字"
    got = {t[0]: t[3] for t in r.recs}
    assert got["id4"] == got["id6"] == ""
    assert [got["id3"], got["id5a"], got["id7a"]] == ["之", "安", "恩"]
    assert "".join(got[f"id{s}"] for s in range(8, 12)) == "二字以配"


def test_gap_column_rejects_ink_on_text_slot_or_half_row():
    (ln,) = C.parse_lines(LINE)
    us = _manchu_units() + [_cu(99, 9.75, "某")]                   # 多一格落在两个字位之间：切多了
    assert not C.coord_column(sorted(us, key=lambda u: u.g), ln, gap=True).ok
    (plain,) = C.parse_lines("#@ x\n元許衡撰")                      # 行内没有空格位：夹在中间的格不认
    us = [_cu(1, 1.0, "元"), _cu(2, 2.0, "許"), _cu(9, 2.5, "某"), _cu(3, 3.0, "衡"), _cu(4, 4.0, "撰")]
    assert not C.coord_column(us, plain, gap=True).ok


def test_gap_column_needs_carrier_agreement():
    (ln,) = C.parse_lines(LINE)
    units = [C.CellUnit(u.kind, u.slot, u.g, u.ids, {k: "某" for k in u.carrier}) for u in _manchu_units()]
    assert not C.coord_column(units, ln, gap=True).ok


def test_blank_hits_only_flag_cells_when_column_agrees():
    chars = "國語中並無以他字加於"
    recs = [(f"x{k}", k, None, ch, float(k)) for k, ch in enumerate(chars, 1)] + [("x11", 11, None, "", 11.0)]
    legacy = {r[0]: AlignRec(id=r[0], col=9, slot=r[1], align_char=r[3], align_op="equal", ref_run=10)
              for r in recs[:10]}
    legacy["x11"] = AlignRec(id="x11", col=9, slot=11, align_char="之", align_op="equal", ref_run=1)
    assert _coord_conflict(recs, legacy, {})                         # 关：空格位上现役对上「之」→ 整列退回
    hits: list = []
    assert _coord_conflict(recs, legacy, {}, blank_hits=hits) == "" and hits == ["x11"]
    hits = []
    assert _coord_conflict(recs, {}, {"x11": "之"}, blank_hits=hits)  # 库认出字但同列没有别的证据 → 照旧退回
    assert hits == []
    same = {r[0]: r[3] for r in recs[:10]} | {"x11": "之"}
    hits = []
    assert _coord_conflict(recs, {}, same, blank_hits=hits) == "" and hits == ["x11"]
    assert "coord_blank_ink" not in AlignRefParams().model_dump()
    assert AlignRefParams(coord_blank_ink=True).model_dump()["coord_blank_ink"] is True


class _V:
    @staticmethod
    def semantic(c):
        return c


def _rec(i, char=None):
    return SimpleNamespace(id=i, admit=False, channel=None, provenance="", char=char, doubts=["lib_unsure"], evidence={})


def _m(top, cov, verdict="unsure"):
    return SimpleNamespace(candidates=[(top, cov)], verdict=verdict)


def test_blank_ink_pass_releases_unrecognised_ink_as_nonchar():
    p = SeedAdmitParams(blank_ink_nonchar=True)
    col = SimpleNamespace(col=1, chars=[_rec(f"c{k}") for k in range(6)])
    coord = {"c0": "國", "c1": "語", "c2": "中", "c3": "", "c4": "", "c5": ""}
    mmap = {"c0": _m("國", .99), "c1": _m("語", .98), "c2": _m("中", 1.0, "same"),
            "c3": _m("駐", .77, "diff"), "c4": _m("之", .97), "c5": _m("改", .7, "diff")}
    n = _blank_ink_pass(p, [col], mmap, coord, frozenset({"c5"}), _V)
    assert n == 1
    r3, r4, r5 = col.chars[3:]
    assert r3.admit and r3.char is None and r3.channel == "blank_ink" and r3.evidence["lane"]["nonchar"]
    assert not r4.admit                                              # 库有把握（cov ≥ 0.9）：可能是整理本漏字，留审
    assert not r5.admit                                              # 坐标冲突格不碰
    assert "blank_ink_nonchar" not in SeedAdmitParams().model_dump()


def test_blank_ink_pass_skips_columns_that_do_not_line_up():
    p = SeedAdmitParams(blank_ink_nonchar=True)
    col = SimpleNamespace(col=1, chars=[_rec(f"c{k}") for k in range(5)])
    coord = {"c0": "國", "c1": "語", "c2": "中", "c3": "並", "c4": ""}
    mmap = {"c0": _m("某", .9), "c1": _m("語", .9), "c2": _m("某", .9), "c3": _m("某", .9), "c4": _m("駐", .6, "diff")}
    assert _blank_ink_pass(p, [col], mmap, coord, frozenset(), _V) == 0


def test_blank_ink_nonchar_is_skipped_in_text_stream():
    """判非字放行的格不进文本（随整理本不出字），不写 □。"""
    from open_guji_cv.products.kinds.cells import CellRec
    from open_guji_cv.products.kinds.recog import AdmitRec
    from open_guji_cv.report.slots import _to_slot
    cell = CellRec(slot=4, pos=4, y0=0, y1=0, x0=0, x1=0, kind="char", sub=None, order=4)
    rec = AdmitRec(id="b:1:1:4", slot=4, sub=None, admit=True, char=None, reading=None, channel="blank_ink",
                   doubts=["blank_ink"], evidence={"lane": {"lane": "blank_ink", "nonchar": True}})
    s = _to_slot("b", 1, 1, rec, cell)
    assert s.excluded and not s.unreadable
