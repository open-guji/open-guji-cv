# -*- coding: utf-8 -*-
"""Step5-a 每格预算超时（`guard="timeout"`，overview#493）：Step7 任何通道都不放行，落人审并记 `glyph_timeout`。"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import (make_book, make_ctx, page_align_ref, page_decision,
                     page_match, write_product)
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL, SLOT = "tbook", 1, 1, 7


def _run(tmp_path, monkeypatch, **match):
    """整理本、上下文（margin 高）、库候选三路都指向「明」——不带 guard 时必放行。"""
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, **match)]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, char="明", margin=0.9, source="context")]))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
        PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, align_char="明")]))
    ctx.params["seed_admit"] = SeedAdmitParams()
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    (r,) = col.chars
    return r


def test_control_admits_without_timeout(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, verdict="unsure", cov=0.95, wmax=4.0,
             candidates=[("明", 0.95), ("朋", 0.9)])
    assert r.admit and r.char == "明"


def test_timeout_cell_goes_to_review_whatever_the_other_evidence(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, verdict="diff", guard="timeout")
    assert not r.admit and r.channel is None
    assert "glyph_timeout" in r.doubts
    # 带候选的超时记录（不会由 Step5-a 产出，但守住"guard 优先于一切证据"）也一样
    r = _run(tmp_path, monkeypatch, verdict="unsure", cov=0.95, wmax=4.0,
             candidates=[("明", 0.95), ("朋", 0.9)], guard="timeout")
    assert not r.admit and "glyph_timeout" in r.doubts
