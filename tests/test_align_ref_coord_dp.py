# -*- coding: utf-8 -*-
"""`coord_dp`（2026-11-02，史記文淵閣本 B 类对位缺格）：几何配不上时的载体字单调对齐。"""
from __future__ import annotations

from open_guji_cv.steps import align_ref_coord as C


def _units(chars: str, skip_at: int | None = None, extra_at: int | None = None):
    us = []
    for i, ch in enumerate(chars):
        if i == skip_at:
            continue
        us.append(C.CellUnit("c", len(us) + 1, float(len(us) + 1), {"": f"p:1:{len(us) + 1}"}, {"": ch}))
    if extra_at is not None:
        us.insert(extra_at, C.CellUnit("c", 99, extra_at + 0.5, {"": "p:1:x"}, {"": "?"}))
    return us


def _text(s: str):
    return [(i, C.Unit("c", ch)) for i, ch in enumerate(s)]


REF = "山東雖亂秦之地可全而有宗廟之祀"


def test_dp_missing_one_cell_still_aligns_the_rest():
    """少一格（并格/漏切）：几何配不上，单调对齐跳过一个整理本字，其余格各得其字。"""
    r = C.coord_dp(_units(REF, skip_at=5), _text(REF))
    assert r is not None and r.ok
    got = {i: ch for i, _sl, _sub, ch, _g in r.recs}
    assert got["p:1:6"] == "地"          # 被漏掉的「之」之后的格没有错位
    assert got["p:1:1"] == "山"


def test_dp_extra_cell_gets_no_ref():
    """多一格（假格）：假格不进 recs（不记空格位）。"""
    r = C.coord_dp(_units(REF, extra_at=4), _text(REF))
    assert r is not None
    assert "p:1:x" not in {i for i, *_ in r.recs}


def test_dp_rejects_low_agreement():
    """载体字与整理本几乎不吻合 → 不认。"""
    assert C.coord_dp(_units("甲乙丙丁戊己庚辛壬癸子丑寅卯"), _text(REF)) is None


# 史記 r53 37:194:3（格线与 r52 同，换字形库 g20 后）：僮格认成「僕」、僕格认成「借」
_R53 = "天子以自媚多從人行至長安虜賣以為僮僕取自脫"
_R53_CARRIER = "天子以自嫄多從人行至長安虜賣以為僕借取自脫"


def test_dp_two_skips_for_one_agree_shifts_without_cost():
    """不扣跳过分：跳一个整理本字＋跳一格，换来僮格吻合「僕」，整理本字错开一格（原行为，留作对照）。"""
    r = C.coord_dp(_units(_R53_CARRIER), _text(_R53))
    got = {i: ch for i, _sl, _sub, ch, _g in r.recs}
    assert got["p:1:17"] == "僕" and "p:1:18" not in got


def test_dp_skip_cost_keeps_column_in_place():
    """`skip_cost` 0.6：两次跳过只换来一处吻合时不错开，僮格配「僮」、僕格配「僕」；门槛按吻合数算。"""
    r = C.coord_dp(_units(_R53_CARRIER), _text(_R53), skip_cost=0.6)
    got = {i: ch for i, _sl, _sub, ch, _g in r.recs}
    assert got["p:1:17"] == "僮" and got["p:1:18"] == "僕" and got["p:1:5"] == "媚"
    assert r.agree == len(_R53) - 3


def test_dp_skip_cost_still_skips_for_real_missing_cell():
    """真少一格／多一格时，错开后吻合的是后面整段，扣分照样跳。"""
    r = C.coord_dp(_units(REF, skip_at=5), _text(REF), skip_cost=0.6)
    got = {i: ch for i, _sl, _sub, ch, _g in r.recs}
    assert got["p:1:6"] == "地" and got["p:1:1"] == "山"
    r = C.coord_dp(_units(REF, extra_at=4), _text(REF), skip_cost=0.6)
    assert r is not None and "p:1:x" not in {i for i, *_ in r.recs}


def test_dp_skip_cost_topk_credit_holds_place():
    """史記 r53 35:84:2：大格认成「太」（前几名有「大」）、夫格认成「大」（前几名有「夫」）。
    只看载体字时错开一格能多一处吻合；记上前几名候选分后原位分更高，不错开。"""
    ref = "韓安國免詔拜為御史大夫自為吏未言案人"
    car = "韓安國免詔拜為御史太大自為吏未言案人"
    us = _units(car)
    topk = {u.ids[""]: (u.carrier[""], ref[i]) for i, u in enumerate(us)}
    r = C.coord_dp(us, _text(ref), skip_cost=0.6, topk=topk)
    got = {i: ch for i, _sl, _sub, ch, _g in r.recs}
    assert got["p:1:10"] == "大" and got["p:1:11"] == "夫"


def test_dp_skip_cost_off_by_default_and_not_in_dump():
    from open_guji_cv.steps.align_ref import AlignRefParams
    assert "coord_dp_skip_cost" not in AlignRefParams().model_dump()
    assert AlignRefParams(coord_dp_skip_cost=0.6).model_dump()["coord_dp_skip_cost"] == 0.6


def test_dp_params_off_by_default_and_not_in_dump():
    from open_guji_cv.steps.align_ref import AlignRefParams
    p = AlignRefParams()
    assert p.coord_dp is False and "coord_dp" not in p.model_dump()
    assert AlignRefParams(coord_dp=True).model_dump()["coord_dp"] is True


def test_layout_slots_grow_off_by_default_and_not_in_dump():
    from open_guji_cv.steps.row_segment import RowSegmentParams
    assert RowSegmentParams().layout_slots_grow is False
    assert "layout_slots_grow" not in RowSegmentParams().model_dump()
    assert RowSegmentParams(layout_slots_grow=True).model_dump()["layout_slots_grow"] is True


# ── coord_dp_flat（2026-11-03）：逐字字序对齐 ──

def _jz_units(right: str, left: str, start: int = 1):
    """一段夹注：第 k 行 a＝right[k]、b＝left[k]（左行短时只有 a）。"""
    us = []
    for k in range(max(len(right), len(left))):
        ids, car = {}, {}
        if k < len(right):
            ids["a"], car["a"] = f"p:1:{start + k}a", right[k]
        if k < len(left):
            ids["b"], car["b"] = f"p:1:{start + k}b", left[k]
        us.append(C.CellUnit("n", start + k, float(start + k), ids, car))
    return us


def _jz_text(right: str, left: str):
    return [(k, C.Unit("n", right[k] if k < len(right) else "", left[k] if k < len(left) else ""))
            for k in range(max(len(right), len(left)))]


def test_flat_jiazhu_split_point_differs():
    """写本右行比整理本「|」多写一字：按行单元配整段错开，逐字字序仍一一对上。"""
    txt = "古文曰盤庚自奄遷于北蒙曰殷虛南去鄴三十里"
    units = _jz_units(txt[:11], txt[11:])            # 图上右行 11 字
    text = _jz_text(txt[:10], txt[10:])              # 整理本右行 10 字
    r = C.coord_dp_flat(units, text)
    assert r is not None and r.note == "dp_flat"
    got = {i: ch for i, _sl, _sub, ch, _g in r.recs}
    assert got["p:1:11a"] == "蒙" and got["p:1:1b"] == "曰"


def test_flat_many_fake_cells_skipped():
    """题署行：印泥假格夹在字之间，多过 coord_dp 的两次跳过，逐字对齐仍认；假格不给字。"""
    ref = "漢太史令司馬遷撰"
    us, k = [], 0
    for ch in "漢??太??史令司馬遷?撰":
        k += 1
        us.append(C.CellUnit("c", k, float(k), {"": f"p:1:{k}"}, {"": ch}))
    assert C.coord_dp(us, _text(ref)) is None
    r = C.coord_dp_flat(us, _text(ref))
    assert r is not None
    got = {i: ch for i, _sl, _sub, ch, _g in r.recs}
    assert got["p:1:1"] == "漢" and got["p:1:13"] == "撰"
    assert "p:1:2" not in got


def test_flat_rejects_unrelated_column():
    assert C.coord_dp_flat(_units("甲乙丙丁戊己庚辛壬癸子丑寅卯"), _text(REF)) is None


def test_flat_param_off_by_default_and_not_in_dump():
    from open_guji_cv.steps.align_ref import AlignRefParams
    assert "coord_dp_flat" not in AlignRefParams().model_dump()
    assert AlignRefParams(coord_dp_flat=True).model_dump()["coord_dp_flat"] is True
