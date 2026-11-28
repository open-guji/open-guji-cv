# -*- coding: utf-8 -*-
"""两个缺省关的小闸（全唐文 r11 复核，形近字线 11-05）。

- `ref_lib_coord_dissent`：`ref_lib` 放行前，坐标对位给了实字、与现役对位字语义不同 → 不放，记
  `ref_lib_coord_dissent`、落人审（r11：去借库后库缺 麒／褚／俘，库首位与现役对位一起错成 麟／諸／俾）。
- `replace_form_edge_exclude`：`replace_form: lib` 不把整理本字换成假边表里的另一半（往→住）。
摆法照抄 `test_seed_admit_ref_lib_diff_guard.py` 与 `test_seed_admit_solo_replace_0928.py`。
"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_match, write_product
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.kinds.recog import AlignRec, CoordRec, PageAlignRef
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _LANE_HARD, _edge_pair_excluded

BOOK, PAGE, COL, SLOT = "tbook", 1, 1, 15
CID = f"{BOOK}:{PAGE}:{COL}:{SLOT}"


def _run(tmp_path, monkeypatch, *, cands, align_char, align_op, coord=None, verdict="unsure", params=None):
    ctx = make_ctx(tmp_path, make_book(BOOK, iron_gate=False), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, verdict=verdict, cov=cands[0][1], wmax=25.81,
                                        candidates=cands)]))
    write_product(ctx, "align_ref", PAGE, align_ref=PageAlignRef(
        page=PAGE, anchored=True,
        chars=[AlignRec(id=CID, col=COL, slot=SLOT, align_char=align_char, align_op=align_op)],
        coord=[CoordRec(id=CID, col=COL, slot=SLOT, ref_char=coord)] if coord is not None else []))
    ctx.params["seed_admit"] = SeedAdmitParams(**{"shadow_veto": False, "group_flow": ("jys",), **(params or {})})
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    (r,) = col.chars
    return r


RL = dict(cands=[("變", 0.9443), ("泊", 0.939)], align_char="變", align_op="replace")


def test_coord_dissent_off_by_default(tmp_path, monkeypatch):
    assert SeedAdmitParams().ref_lib_coord_dissent is False
    r = _run(tmp_path, monkeypatch, **RL, coord="泊")
    assert r.admit and r.channel == "ref_lib" and r.char == "變"


def test_coord_dissent_blocks(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, **RL, coord="泊", params={"ref_lib_coord_dissent": True})
    assert not r.admit and "ref_lib_coord_dissent" in r.doubts, (r.channel, r.char, r.doubts)
    assert "ref_lib_coord_dissent" in _LANE_HARD


def test_coord_agree_or_missing_still_admits(tmp_path, monkeypatch):
    for coord in ("變", None, "", "〓"):
        r = _run(tmp_path, monkeypatch, **RL, coord=coord, params={"ref_lib_coord_dissent": True})
        assert r.admit and r.channel == "ref_lib" and r.char == "變", coord


def test_params_not_in_dump_when_off():
    d = SeedAdmitParams().model_dump()
    assert "ref_lib_coord_dissent" not in d and "replace_form_edge_exclude" not in d
    d = SeedAdmitParams(ref_lib_coord_dissent=True, replace_form_edge_exclude=True).model_dump()
    assert d["ref_lib_coord_dissent"] is True and d["replace_form_edge_exclude"] is True


def test_edge_pair_excluded_reads_table():
    assert _edge_pair_excluded("往", "住") and _edge_pair_excluded("住", "往")
    assert not _edge_pair_excluded("既", "旣")


# replace_form: lib 摆法同 test_seed_admit_solo_replace_0928（旣/既 不在假边表：照换）
def test_replace_form_lib_not_excluded_still_swaps(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=[("既", 0.97), ("當", 0.90)], align_char="旣", align_op="replace",
             params={"replace_form": "lib", "replace_form_edge_exclude": True})
    assert r.admit and r.channel == "match_replace" and r.char == "既"


def test_replace_form_lib_excluded_keeps_align(tmp_path, monkeypatch):
    import open_guji_cv.steps.seed_admit as sa
    monkeypatch.setattr(sa, "_edge_pair_excluded", lambda a, b: {a, b} == {"既", "旣"})
    kw = dict(cands=[("既", 0.97), ("當", 0.90)], align_char="旣", align_op="replace")
    r = _run(tmp_path, monkeypatch, **kw, params={"replace_form": "lib"})
    assert r.char == "既"                                     # 开关关：照旧换库形
    r = _run(tmp_path, monkeypatch, **kw, params={"replace_form": "lib", "replace_form_edge_exclude": True})
    assert r.admit and r.channel == "match_replace" and r.char == "旣"
