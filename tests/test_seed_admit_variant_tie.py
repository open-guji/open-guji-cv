# -*- coding: utf-8 -*-
"""Step7 异体并列放行（`variant_tie`，Y1 / overview#471）：top1 与近邻是同一个字的两个码位而并列 → 放行 top1；缺省关。"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_decision, page_match, write_product
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1


def _run(tmp_path, monkeypatch, cands, params=None, guard=None):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, col=COL, recs=[
        dict(slot=1, verdict="unsure", cov=cands[0][1], wmax=10.0, candidates=list(cands), guard=guard)]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[dict(slot=1, char=None, margin=0.1, source="prior")]))
    ctx.params["seed_admit"] = SeedAdmitParams(**(params or {}))
    return STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns[0].chars[0]


ON = {"variant_tie": True}


def test_default_off(tmp_path, monkeypatch):
    assert not _run(tmp_path, monkeypatch, [("𢑴", 0.975), ("彝", 0.972)]).admit
    assert "variant_tie" not in SeedAdmitParams().model_dump()


def test_variant_pair_released_with_top1(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, [("𢑴", 0.975), ("彝", 0.972)], ON)
    assert r.admit and r.channel == "variant_tie" and r.char == "𢑴"


def test_extra_group(tmp_path, monkeypatch):
    c = [("𫎇", 0.98), ("蒙", 0.975)]
    assert not _run(tmp_path, monkeypatch, c, ON).admit
    assert _run(tmp_path, monkeypatch, c, {**ON, "variant_tie_extra": "𫎇蒙"}).char == "𫎇"


def test_non_variant_neighbour_blocks(tmp_path, monkeypatch):
    assert not _run(tmp_path, monkeypatch, [("𢑴", 0.975), ("彝", 0.972), ("家", 0.971)], ON).admit


def test_low_cov_and_guard_block(tmp_path, monkeypatch):
    assert not _run(tmp_path, monkeypatch, [("𢑴", 0.95), ("彝", 0.94)], ON).admit
    assert not _run(tmp_path, monkeypatch, [("𢑴", 0.975), ("彝", 0.972)], ON, guard="never_match").admit


def test_confusable_top1_blocked(tmp_path, monkeypatch):
    assert not _run(tmp_path, monkeypatch, [("土", 0.98), ("士", 0.975)], ON).admit
