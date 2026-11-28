"""vis3 影子（`seed_admit.vis3_shadow`）缺省关时产物逐字节不变（验收标准 S10，CV4 2026-11-28）。

三条：①缺省参数的收尾产物 dump 里没有 vis3_shadow 键、不读 glyph_analyzer；②同页有 glyph_analyzer 产物（带 vis）时
缺省关的产物与没有它时逐字节同；③开了以后只多一条 `evidence.vis3_shadow`——去掉它后与关着的产物逐字节同（只记录、不改放行）。
"""
from __future__ import annotations

import copy
import json

import open_guji_cv.steps  # noqa: F401
import pytest
from helpers import make_book, make_ctx, page_decision, page_match, write_product
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.kinds.read import ColumnFinal, FinalCand, FinalRec, PageFinal

pytestmark = pytest.mark.usefixtures("no_cnn", "seed_admit_switches_off")

BOOK, PAGE, COL = "tbook", 1, 1
_RECS = [
    dict(slot=1, verdict="unsure", cov=0.995, wmax=0.0, candidates=[("甲", 0.995)]),
    dict(slot=2, verdict="unsure", cov=0.96, wmax=0.0, candidates=[("乙", 0.96)]),
]


def _run(tmp_path, monkeypatch, *, params=None, with_final=False):
    book = make_book(BOOK, **({"params": params} if params else {}))
    ctx = make_ctx(tmp_path, book, monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=_RECS, col=COL))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, recs=[dict(slot=2, char="乙", margin=0.8, source="context")], col=COL))
    if with_final:
        rec = FinalRec(id=f"{BOOK}:{PAGE}:{COL}:1", slot=1, cands=[FinalCand(char="甲")],
                       vis={"status": "hit", "char": "乙", "other": False, "conf": "high"})
        write_product(ctx, "glyph_analyzer", PAGE, glyph_analyzer=PageFinal(
            page=PAGE, columns=[ColumnFinal(col=COL, chars=[rec])]))
    return STEPS["char_decide"].run_page(ctx, PAGE)["char_decide"]


def _dump(sa) -> str:
    return json.dumps(sa.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)


def test_default_off_same_with_or_without_glyph_analyzer(tmp_path, monkeypatch):
    a = _dump(_run(tmp_path / "a", monkeypatch))
    b = _dump(_run(tmp_path / "b", monkeypatch, with_final=True))
    assert a == b and "vis3_shadow" not in a


def test_param_not_in_default_dump():
    from open_guji_cv.steps.seed_admit_params import SeedAdmitParams
    assert SeedAdmitParams().vis3_shadow is False
    assert "vis3_shadow" not in SeedAdmitParams().model_dump(mode="json", context={"hash": True})


def test_on_only_adds_evidence(tmp_path, monkeypatch):
    off = _run(tmp_path / "off", monkeypatch, with_final=True)
    on = _run(tmp_path / "on", monkeypatch, params={"seed_admit": {"vis3_shadow": True}}, with_final=True)
    d_on = copy.deepcopy(on.model_dump(mode="json"))
    n = 0
    for col in d_on["columns"]:
        for r in col["chars"]:
            if "vis3_shadow" in (r.get("evidence") or {}):
                r["evidence"].pop("vis3_shadow")
                n += 1
    assert n == 1, "开着时应只在 glyph_analyzer 带 vis 的那一格写 vis3_shadow"
    assert json.dumps(d_on, sort_keys=True, ensure_ascii=False) == _dump(off)
