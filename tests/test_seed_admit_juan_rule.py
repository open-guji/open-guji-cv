# -*- coding: utf-8 -*-
"""Step7「数字＋卷」放行（`juan_rule`，Y1 / overview#454）。

vol05 与整理本冲突 45 格里 42 格是书名后的「一卷」：库 top1 卷 cov≥0.98，整理本排异体
「巻」，被 `context_vs_ref` 拦。规则只在：库 top1=卷、cov≥门槛、前一正文字是数字、整理本
字缺省或为 卷／巻 时放行；缺省关。
"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import (make_book, make_ctx, page_align_ref, page_decision,
                     page_match, write_product)
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1


def _run(tmp_path, monkeypatch, *, prev="一", cov=0.984, top="卷", align="巻",
         params=None, sub=None):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    recs = [dict(slot=1, verdict="same", char=prev, cov=0.999, wmax=10.0,
                 candidates=[(prev, 0.999)]),
            dict(slot=2, verdict="unsure", cov=cov, wmax=10.0,
                 candidates=[(top, cov)], **({"sub": sub} if sub else {}))]
    write_product(ctx, "glyph_match", PAGE,
                  glyph_match=page_match(PAGE, BOOK, col=COL, recs=recs))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[dict(slot=2, char="卷", margin=0.9, source="context")]))
    arecs = [dict(slot=1, align_char=prev)]
    if align is not None:
        arecs.append(dict(slot=2, align_char=align, align_op="replace"))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(PAGE, BOOK, recs=arecs, col=COL))
    ctx.params["seed_admit"] = SeedAdmitParams(**(params or {}))
    sa = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    return sa.columns[0].chars[1]


ON = {"juan_rule": True}


def test_rule_admits_juan_after_number(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, params=ON)
    assert r.admit and r.channel == "juan" and r.char == "卷" and r.doubts == []


def test_default_off_keeps_old_behaviour(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch)
    assert not r.admit and "context_vs_ref" in r.doubts


def test_off_params_dump_unchanged():
    assert "juan_rule" not in SeedAdmitParams().model_dump()
    assert "juan_cov" not in SeedAdmitParams().model_dump()
    assert SeedAdmitParams(juan_rule=True).model_dump()["juan_cov"] == 0.98


def test_low_cov_not_admitted(tmp_path, monkeypatch):
    assert not _run(tmp_path, monkeypatch, cov=0.977, params=ON).admit


def test_prev_not_number_not_admitted(tmp_path, monkeypatch):
    assert not _run(tmp_path, monkeypatch, prev="書", params=ON).admit


def test_top1_not_juan_not_admitted(tmp_path, monkeypatch):
    assert not _run(tmp_path, monkeypatch, top="巷", params=ON).admit


def test_ref_says_other_char_not_admitted(tmp_path, monkeypatch):
    """整理本给了别的字（不是 卷／巻）——整理本说了不同一律不放。"""
    assert not _run(tmp_path, monkeypatch, align="巷", params=ON).admit


def test_no_ref_still_admitted(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, align=None, params=ON)
    assert r.admit and r.channel in ("juan", "context")


def test_jiazhu_cell_skipped(tmp_path, monkeypatch):
    assert not _run(tmp_path, monkeypatch, sub="a", params=ON).admit
