# -*- coding: utf-8 -*-
"""Step7 `rare_cp_ctx_review`（2026-10-10，overview#437 异体组方案 A）：罕用码位 × `context` 通道落审。

vol04／vol05 有标签放行格里，放行字不在 U+4E00–9FFF 的错率 17%／5.6%（常用区 4.5%／1.3%），
错的 11 格里 `context` 通道占 8（𠮓→變、𣼣→漏、𠃜→尸…）。只降级、不改字、不放行；缺省关，关时不进 dump。
"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_decision, page_match, write_product
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _rare_cp_ctx_pass

BOOK, PAGE, COL, SLOT = "tbook", 1, 1, 15


def _run(tmp_path, monkeypatch, *, char: str, params: dict | None = None):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, verdict="diff", cov=0.50, wmax=10.0,
                                        candidates=[("某", 0.50)])]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, char=char, margin=0.90, source="context")]))
    ctx.params["seed_admit"] = SeedAdmitParams(**{"context_garble_guard": False, **(params or {})})
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    (r,) = col.chars
    return r


def test_default_off_admits_rare(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, char="𠮓")
    assert r.admit and r.channel == "context" and r.char == "𠮓"


def test_on_rare_codepoint_context_goes_to_review(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, char="𠮓", params={"rare_cp_ctx_review": True})
    assert not r.admit and r.channel is None and r.provenance == ""
    assert r.char == "𠮓"                                  # 只降级，不改字
    assert "rare_cp_context" in r.doubts
    assert r.evidence["rare_cp_context"] == {"char": "𠮓", "cp": "U+20B93"}


def test_on_common_codepoint_context_still_admitted(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, char="變", params={"rare_cp_ctx_review": True})
    assert r.admit and r.channel == "context" and r.char == "變"


def test_off_params_dump_unchanged():
    assert "rare_cp_ctx_review" not in SeedAdmitParams().model_dump()
    assert SeedAdmitParams(rare_cp_ctx_review=True).model_dump()["rare_cp_ctx_review"] is True
    from open_guji_cv.core.engine import params_hash
    assert params_hash(SeedAdmitParams()) == params_hash(SeedAdmitParams(rare_cp_ctx_review=False))
    assert params_hash(SeedAdmitParams()) != params_hash(SeedAdmitParams(rare_cp_ctx_review=True))


class _R:
    def __init__(self, **kw):
        self.id, self.char, self.admit, self.channel = "x", "𠮓", True, "context"
        self.provenance, self.doubts, self.evidence = "context", [], {}
        self.__dict__.update(kw)


class _Col:
    def __init__(self, *recs):
        self.chars = list(recs)


def test_pass_only_touches_context_channel_and_not_human():
    keep = [_R(channel="match_replace"), _R(channel="match_solo"), _R(channel="coord_fallback"),
            _R(channel="ref_ctx", provenance="context"), _R(provenance="human", channel="human"),
            _R(channel="context", provenance="human"), _R(char="變"), _R(admit=False, channel=None)]
    hit = _R()
    assert _rare_cp_ctx_pass([_Col(*keep, hit)], {}) == 1
    assert not hit.admit and hit.channel is None
    assert all((k.admit, k.channel) == (k0.admit, k0.channel)
               for k, k0 in zip(keep, [_R(channel="match_replace"), _R(channel="match_solo"),
                                        _R(channel="coord_fallback"), _R(channel="ref_ctx"),
                                        _R(channel="human"), _R(channel="context"), _R(char="變"),
                                        _R(admit=False, channel=None)]))
