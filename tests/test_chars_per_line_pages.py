# -*- coding: utf-8 -*-
"""按页每列字数 `chars_per_line_pages`（CV2 2026-11-27，朱楓林集序页六行十四字、正文九行二十字）。自造数据。"""
from __future__ import annotations

import pytest

import open_guji_cv.steps  # noqa: F401
from helpers import make_book
from open_guji_cv.core.book import _load_cpl_pages
from open_guji_cv.core.engine import _self_payload
from open_guji_cv.core.step import CPL_PAGES_STEPS, STEPS, _cpl_page_view


def test_load():
    assert _load_cpl_pages(None) == {}
    assert _load_cpl_pages({"2-4": 14, 9: 12}) == {2: 14, 3: 14, 4: 14, 9: 12}
    with pytest.raises(ValueError):
        _load_cpl_pages({2: 0})


def test_at():
    b = make_book("tbook", chars_per_line=20, chars_per_line_pages={3: 14})
    assert b.chars_per_line_at(3) == 14 and b.chars_per_line_at(4) == 20 and b.chars_per_line_at(None) == 20


@pytest.mark.parametrize("sid", sorted(CPL_PAGES_STEPS))
def test_steps_wrapped(sid):
    assert getattr(type(STEPS[sid]).run_page, "_cpl_page_view", False)


def test_page_view_swaps_and_restores():
    seen = []

    class Ctx:
        book = make_book("tbook", chars_per_line=20, chars_per_line_pages={3: 14})

    f = _cpl_page_view(lambda self, ctx, page: seen.append(ctx.book.chars_per_line))
    ctx = Ctx()
    b = ctx.book
    f(None, ctx, 3)
    f(None, ctx, 4)
    assert seen == [14, 20] and ctx.book is b and b.chars_per_line == 20


def test_fingerprint_unchanged_without_table():
    b0 = make_book("tbook", chars_per_line=20)
    b1 = make_book("tbook", chars_per_line=20, chars_per_line_pages={3: 14})
    for sid in CPL_PAGES_STEPS:
        st = STEPS[sid]
        assert "cpl_pages" not in _self_payload(st, b0, "x")
        assert _self_payload(st, b1, "x")["cpl_pages"] == {"3": 14}
    assert "cpl_pages" not in _self_payload(STEPS["glyph_match"], b1, "x")
