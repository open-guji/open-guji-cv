"""seed_admit 共识升档 same 的库字放行（`SeedAdmitParams.consensus_lib_cov`，缺省关）。

实例取自全唐文 f4 016–030 待审（字形线 11-11 看图）：共识升档判 𥳑 cov 0.969–0.98，
`consensus_fallback` 退回 unsure 后卡在准入；cov≥0.97 的 78 格看图 0 错。
"""
from __future__ import annotations

import pytest

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_decision, page_match, write_product
from open_guji_cv.core.engine import params_hash
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.seed_admit import SeedAdmitParams, SeedAdmitStep

BOOK, PAGE, COL = "tbook", 1, 1
ON = {"consensus_fallback": True, "consensus_lib_cov": 0.97}
CONS = dict(cands=(("𥳑", 0.975), ("蘭", 0.90)), verdict="same", via="consensus:111")


def _run(tmp_path, monkeypatch, *, cands, params=None, guard=None, verdict="unsure", via=None):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[dict(slot=1, verdict=verdict, char=cands[0][0] if verdict == "same" else None,
                                         cov=cands[0][1], wmax=3.0, guard=guard, candidates=list(cands), via=via)]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[dict(slot=1, char=None, margin=0.0, source="prior")]))
    ctx.params["seed_admit"] = SeedAdmitParams(**{"patch_missing": "skip", "consensus_fallback": True,
                                                   **(params or {})})
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    (r,) = col.chars
    return r


def test_params_off_is_invisible(tmp_path):
    db = str(tmp_path / "g.db")
    off = SeedAdmitParams(db_path=db)
    assert "consensus_lib_cov" not in off.model_dump()
    sp, pt = SeedAdmitStep.spec.soft_params, SeedAdmitStep.spec.path_params
    on = SeedAdmitParams(db_path=db, consensus_lib_cov=0.97)
    assert on.model_dump()["consensus_lib_cov"] == 0.97
    assert params_hash(on, sp, pt) != params_hash(off, sp, pt)


def test_off_leaves_cell_in_review(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, **CONS)
    assert not r.admit and "consensus_lib" not in r.evidence


def test_on_admits_lib_char(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, params=ON, **CONS)
    assert r.admit and r.channel == "consensus_lib" and r.char == "𥳑" and r.doubts == []
    assert r.evidence["no_glyph_lib"] is True
    assert r.evidence["consensus_lib"] == {"lib": "𥳑", "cov": 0.975, "via": "consensus:111"}


@pytest.mark.parametrize("kw", [
    dict(cands=(("𥳑", 0.965), ("蘭", 0.90)), verdict="same", via="consensus:111"),   # 不到门槛
    dict(cands=(("𥳑", 0.975), ("蘭", 0.90)), verdict="unsure", via=None),            # 普通 unsure：同门槛错率 35%
    dict(cands=(("己", 0.975), ("已", 0.97)), verdict="same", via="consensus:5"),     # 己已巳 不碰
    dict(cands=(("𥳑", 0.975), ("蘭", 0.90)), verdict="same", via="consensus:111", guard="conflict"),
])
def test_on_keeps_review(tmp_path, monkeypatch, kw):
    r = _run(tmp_path, monkeypatch, params=ON, **kw)
    assert r.channel != "consensus_lib"
