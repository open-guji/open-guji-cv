# -*- coding: utf-8 -*-
"""书级 `codepoints:` 并进语义判等（`codepoint_semantic`）。

vmap 不认 巻/卷、别/別 等码位异体，整理本排了异体、刻本与文意都对的格被 `context_vs_ref`
拦下送审。册配置声明过的对，本步按同一个字算，放行的字落到册指定码位。
"""
from __future__ import annotations

import pytest

import open_guji_cv.steps  # noqa: F401
from helpers import (make_book, make_ctx, page_align_ref, page_decision,
                     page_match, write_product)
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1


def _run(tmp_path, monkeypatch, *, top, align, codepoints, params=None, cov=0.97):
    ctx = make_ctx(tmp_path, make_book(BOOK, codepoints=codepoints), monkeypatch=monkeypatch)
    recs = [dict(slot=1, verdict="same", char="書", cov=0.999, wmax=10.0, candidates=[("書", 0.999)]),
            dict(slot=2, verdict="unsure", cov=cov, wmax=10.0, candidates=[(top, cov)])]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, col=COL, recs=recs))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[dict(slot=2, char=top, margin=0.9, source="context")]))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(PAGE, BOOK, recs=[
        dict(slot=1, align_char="書"), dict(slot=2, align_char=align, align_op="replace")], col=COL))
    ctx.params["seed_admit"] = SeedAdmitParams(**{"patch_missing": "skip", **(params or {})})
    return STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns[0].chars[1]


PAIRS = [("卷", "巻"), ("別", "别"), ("出", "岀"), ("晚", "晩"), ("内", "內")]


@pytest.mark.parametrize("top,variant", PAIRS)
def test_configured_pair_admitted_as_target(tmp_path, monkeypatch, top, variant):
    r = _run(tmp_path, monkeypatch, top=top, align=variant, codepoints={variant: top})
    assert r.admit and r.char == top and "context_vs_ref" not in r.doubts


@pytest.mark.parametrize("top,variant", PAIRS)
def test_unconfigured_book_unchanged(tmp_path, monkeypatch, top, variant):
    r = _run(tmp_path, monkeypatch, top=top, align=variant, codepoints={})
    assert not r.admit and "context_vs_ref" in r.doubts


def test_switch_off_restores_old(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, top="卷", align="巻", codepoints={"巻": "卷"},
             params={"codepoint_semantic": False})
    assert not r.admit and "context_vs_ref" in r.doubts


def test_default_params_dump_unchanged():
    assert "codepoint_semantic" not in SeedAdmitParams().model_dump()
    assert SeedAdmitParams(codepoint_semantic=False).model_dump()["codepoint_semantic"] is False


def test_other_char_still_blocked(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, top="卷", align="券", codepoints={"巻": "卷"})
    assert not r.admit


def test_l2_key_compared_after_codepoint_canon():
    """文意 L2 表的键按书级码位归一再比：邻格放行字与表里只差 巻/卷、别/別，不算上下文变了。"""
    from open_guji_cv.groups.ctx_l3 import CtxL3Backend
    from open_guji_cv.groups.context import CTX_VER, ctx_key
    from open_guji_cv.groups.protocol import JudgeInput, window_from_text
    from open_guji_cv.groups.registry import GROUPS
    spec = GROUPS["ry"]
    table = {"schema": "group_clf/1", "group": "ry", "ctx_ver": CTX_VER,
             "cells": {"c1": {"ctx": ctx_key("三巻", "別行"), "char": "曰", "why": "x"}}}
    book = make_book(BOOK, codepoints={"巻": "卷", "别": "別"})
    cell = JudgeInput(id="c1", ref=None, window=window_from_text("三卷", "别行"))
    be = CtxL3Backend(table)
    assert be.judge(spec, cell).why == "ctx_mismatch"
    v = be.judge(spec, cell, book.canonical_char)
    assert v.char == "曰" and v.why == "x"


pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")   # 老测试按「放行开关缺省全关」造的数据，见 conftest
