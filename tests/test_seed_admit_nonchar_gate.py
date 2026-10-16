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
