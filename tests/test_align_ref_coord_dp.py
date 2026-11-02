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


def test_dp_params_off_by_default_and_not_in_dump():
    from open_guji_cv.steps.align_ref import AlignRefParams
    p = AlignRefParams()
    assert p.coord_dp is False and "coord_dp" not in p.model_dump()
    assert AlignRefParams(coord_dp=True).model_dump()["coord_dp"] is True
