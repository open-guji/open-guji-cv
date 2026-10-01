# -*- coding: utf-8 -*-
"""Step7 库高置信兜底通道 `lib_confident`（2026-09-28，D 高置信落审放宽候选）。

对象是「库判 unsure、Step6 退回先验（人审卡上的『上下文 margin 不足』）」的格；
开关缺省关（`lib_confident_cov=0`），开了也只许多出放行，不碰整理本 replace、
己已巳、形近表里的字、有护栏的格。
"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import (make_book, make_ctx, page_align_ref, page_decision,
                     page_match, write_product)
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _confusable_char

BOOK, PAGE, COL, SLOT = "tbook", 1, 1, 15
TOP, SECOND = "耶", "則"          # 实例取自 vol04:154:3:19（Z10 点名的放宽候选）
ON = {"lib_confident_cov": 0.98, "lib_confident_gap": 0.03}


def _run(tmp_path, monkeypatch, *, cands, verdict="unsure", guard=None,
         source="prior", align=None, params=None):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[
            dict(slot=SLOT, verdict=verdict, cov=cands[0][1], wmax=16.0,
                 guard=guard, candidates=cands),
        ]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[
            dict(slot=SLOT, char=None, margin=0.12, source=source),
        ]))
    if align is not None:
        write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
            PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, **align)]))
    ctx.params["seed_admit"] = SeedAdmitParams(**(params or {}))
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    (r,) = col.chars
    return r


HIGH = [(TOP, 0.993), (SECOND, 0.937)]


def test_fixture_chars_are_not_confusable():
    """夹具前提：耶／則 不在任何形近表里——否则下面的「放行」用例测的是别的东西。"""
    assert not _confusable_char(TOP)


def test_default_off_is_noop(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=HIGH)
    assert r.admit is False and r.channel is None
    assert any("上下文 margin 不足" in d for d in r.doubts)


def test_on_admits_high_confidence_prior_cell(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=HIGH, params=ON)
    assert r.admit is True and r.channel == "lib_confident" and r.char == TOP
    assert r.provenance == "match"


def test_below_cov_or_gap_stays_in_review(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=[(TOP, 0.975), (SECOND, 0.90)], params=ON)
    assert r.admit is False
    r = _run(tmp_path, monkeypatch, cands=[(TOP, 0.993), (SECOND, 0.970)], params=ON)
    assert r.admit is False


def test_replace_align_never_admitted(tmp_path, monkeypatch):
    """整理本说了不同（replace）——vol04:151:5:15 库「理」整理本「埋」那一型——不放。"""
    r = _run(tmp_path, monkeypatch, cands=HIGH, params=ON,
             align={"align_char": "郎", "align_op": "replace"})
    assert r.admit is False and r.channel is None
    assert "replace_align" in r.doubts


def test_context_decided_cell_not_touched(tmp_path, monkeypatch):
    """Step6 自己下了判断（source=context，只是没过 margin 门槛）的格不归这条通道管。"""
    r = _run(tmp_path, monkeypatch, cands=HIGH, params=ON, source="context")
    assert r.channel != "lib_confident"


def test_guard_and_verdicts(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=HIGH, params=ON, guard="conflict")
    assert r.channel != "lib_confident"
    r = _run(tmp_path, monkeypatch, cands=HIGH, params=ON, verdict="diff")
    assert r.channel != "lib_confident"


def test_ji_yi_si_and_confusable_excluded(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=[("已", 0.995), ("田", 0.90)], params=ON)
    assert r.channel != "lib_confident"
    r = _run(tmp_path, monkeypatch, cands=[("諭", 0.995), ("田", 0.90)], params=ON)
    assert r.channel != "lib_confident", "諭 在 NEVER_MATCH_FAMILIES 里，按字就该拦"
