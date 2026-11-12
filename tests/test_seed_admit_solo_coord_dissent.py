# -*- coding: utf-8 -*-
"""Step7 `solo_coord_dissent`（GUJI-750，史记 r49）：match_solo 系放行前看坐标对位。

坐标对位给了实字、与放行字语义不同 → 不放，记 `solo_coord_dissent`（硬疑问）。豁免：坐标字是私用码、
两边都是数字（坐标对位在数字处常漂）、语义同字（异体）。缺省关，关时不进参数 dump。
摆法同 `test_seed_admit_solo_ctx_veto.py`（match_solo 样例）＋ `test_seed_admit_ref_lib_coord_dissent.py`（坐标对位）。
"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_match, write_product
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.kinds.recog import CoordRec, PageAlignRef
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _LANE_HARD, _solo_coord_dissented

BOOK, PAGE, COL, SLOT = "tbook", 1, 1, 7
CID = f"{BOOK}:{PAGE}:{COL}:{SLOT}"
SKIP = {"patch_missing": "skip"}
ON = {**SKIP, "solo_coord_dissent": True}


def _run(tmp_path, monkeypatch, *, cands, coord, params=None):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, verdict="unsure", cov=cands[0][1], wmax=4.0, char=None,
                                        candidates=cands)]))
    write_product(ctx, "align_ref", PAGE, align_ref=PageAlignRef(
        page=PAGE, anchored=False, chars=[],
        coord=[CoordRec(id=CID, col=COL, slot=SLOT, ref_char=coord)] if coord is not None else []))
    ctx.params["seed_admit"] = SeedAdmitParams(**{"shadow_veto": False, **(params or {})})
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    (r,) = col.chars
    return r


C1 = [("陪", 0.9930), ("培", 0.9100)]


def test_default_off_admits(tmp_path, monkeypatch):
    assert SeedAdmitParams().solo_coord_dissent is False
    r = _run(tmp_path, monkeypatch, cands=C1, coord="倍", params=SKIP)
    assert r.admit and r.channel == "match_solo" and r.char == "陪"


def test_dissent_blocks(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=C1, coord="倍", params=ON)
    assert not r.admit and "solo_coord_dissent" in r.doubts, (r.channel, r.doubts)
    assert "solo_coord_dissent" in _LANE_HARD


def test_agree_missing_blank_still_admit(tmp_path, monkeypatch):
    for coord in ("陪", None, "", "〓"):
        r = _run(tmp_path, monkeypatch, cands=C1, coord=coord, params=ON)
        assert r.admit and r.channel == "match_solo", coord


def test_exemptions(tmp_path, monkeypatch):
    # 坐标字是私用码：不拦
    r = _run(tmp_path, monkeypatch, cands=[("冡", 0.9941), ("冢", 0.9)], coord="", params=ON)
    assert r.admit and r.channel == "match_solo"
    # 两边都是数字：不拦（坐标对位在数字处常漂）
    r = _run(tmp_path, monkeypatch, cands=[("二", 0.9991), ("三", 0.90)], coord="三", params=ON)
    assert r.admit and r.channel == "match_solo" and r.char == "二"


def test_params_not_in_dump_when_off():
    assert "solo_coord_dissent" not in SeedAdmitParams().model_dump()
    assert SeedAdmitParams(solo_coord_dissent=True).model_dump()["solo_coord_dissent"] is True


class _IdMap:
    def semantic(self, c):
        return c


class _R:
    def __init__(self, id, char, verdict, cands):
        self.id, self.char, self.verdict, self.candidates = id, char, verdict, cands


def test_dissented_function_boundaries():
    r = _R("x", None, "unsure", [("陪", 0.99), ("倍", 0.5)])
    assert _solo_coord_dissented(r, _IdMap(), {"x": "倍"})
    assert not _solo_coord_dissented(r, _IdMap(), {"x": "陪"})
    assert not _solo_coord_dissented(r, _IdMap(), {"x": "〓"})
    assert not _solo_coord_dissented(r, _IdMap(), {})
    assert not _solo_coord_dissented(_R("x", None, "unsure", []), _IdMap(), {"x": "倍"})
    # 库 same 取库字
    assert not _solo_coord_dissented(_R("x", "倍", "same", [("陪", 0.99)]), _IdMap(), {"x": "倍"})
