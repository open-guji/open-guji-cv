# -*- coding: utf-8 -*-
"""Step7 非字过滤（`nonchar_gate`，Y1 / overview#454 第4条）：已放行格带 `char_index` 的
`bad_seg`／`rule_bar` 标记，或放行字是单笔画字符 → 撤回放行落人审；缺省关。"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_chars, page_match, write_product
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL, SLOT = "tbook", 1, 1, 3


def _run(tmp_path, monkeypatch, *, char="之", flags=(), params=None):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, verdict="same", char=char, cov=0.999,
                                        wmax=10.0, candidates=[(char, 0.999)])]))
    write_product(ctx, "cell_shrink", PAGE, char_index=page_chars(
        PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, ink_ratio=0.3, flags=list(flags))]))
    ctx.params["seed_admit"] = SeedAdmitParams(**(params or {}))
    sa = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    return sa.columns[0].chars[0]


ON = {"nonchar_gate": True}


def test_default_off_unchanged(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, flags=["bad_seg"])
    assert r.admit
    assert "nonchar_gate" not in SeedAdmitParams().model_dump()


def test_flag_bad_seg_returns_to_review(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, flags=["bad_seg"], params=ON)
    assert not r.admit and "nonchar" in r.doubts


def test_flag_rule_bar_returns_to_review(tmp_path, monkeypatch):
    assert not _run(tmp_path, monkeypatch, flags=["rule_bar"], params=ON).admit


def test_stroke_char_returns_to_review(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, char="丨", params=ON)
    assert not r.admit and "nonchar" in r.doubts


def test_other_flags_and_normal_char_untouched(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, flags=["boundary_ink", "jiazhu"], params=ON)
    assert r.admit and r.channel


def test_one_is_not_a_stroke_char(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch, char="一", params=ON).admit


# ---- nonchar_ctx_strokes（GUJI-156）：只撤 context 通道的单笔画字 ----

def _run_ctx(tmp_path, monkeypatch, *, char, with_ctx, params):
    from helpers import page_decision
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    if with_ctx:   # 库不确定、上下文给字 → context 通道
        write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
            PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, verdict="unsure", cov=0.9, wmax=10.0,
                                            candidates=[(char, 0.9)])]))
        write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
            PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, char=char, margin=0.9, source="context")]))
    else:          # 库高置信 → match 通道
        write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
            PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, verdict="same", char=char, cov=0.999,
                                            wmax=10.0, candidates=[(char, 0.999)])]))
    write_product(ctx, "cell_shrink", PAGE, char_index=page_chars(
        PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, ink_ratio=0.3, flags=[])]))
    ctx.params["seed_admit"] = SeedAdmitParams(**{"patch_missing": "skip", **params})
    return STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns[0].chars[0]


CTX_ON = {"nonchar_gate": True, "nonchar_ctx_strokes": "一乀乁乚乛"}


def test_ctx_strokes_default_empty_and_not_dumped():
    assert SeedAdmitParams().nonchar_ctx_strokes == ""
    assert "nonchar_ctx_strokes" not in SeedAdmitParams(nonchar_gate=True).model_dump()
    assert "nonchar_ctx_strokes" in SeedAdmitParams(**CTX_ON).model_dump()


def test_ctx_one_stays_admitted_when_param_empty(tmp_path, monkeypatch):
    r = _run_ctx(tmp_path, monkeypatch, char="一", with_ctx=True, params=ON)
    assert r.admit and r.channel == "context"


def test_ctx_one_returns_to_review(tmp_path, monkeypatch):
    r = _run_ctx(tmp_path, monkeypatch, char="一", with_ctx=True, params=CTX_ON)
    assert not r.admit and "nonchar" in r.doubts


def test_ctx_strokes_leave_other_channels_alone(tmp_path, monkeypatch):
    r = _run_ctx(tmp_path, monkeypatch, char="一", with_ctx=False, params=CTX_ON)
    assert r.admit and r.channel != "context"


def test_ctx_strokes_need_gate(tmp_path, monkeypatch):
    r = _run_ctx(tmp_path, monkeypatch, char="一", with_ctx=True,
                 params={"nonchar_ctx_strokes": "一"})
    assert r.admit
