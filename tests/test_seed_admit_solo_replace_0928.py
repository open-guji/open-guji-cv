# -*- coding: utf-8 -*-
"""Step7 书级收紧三参数（2026-09-28，overview#155 D：全唐文 match_solo / match_replace 单独核）。

- `off_channels`：关掉 `admission_decision` 的某几条通道，判决作废、记 `channel_off`；
- `solo_confusable_guard`：match_solo 系的库 top1 在形近表里就落审（`solo_confusable`）；
- `replace_form`：match_replace 整理本字与库 top1 字面不同时取整理本（align，旧行为）
  ／取库形（lib）／落审（review）。

三个缺省值都等于旧行为。
"""
from __future__ import annotations

import pytest

import open_guji_cv.steps  # noqa: F401
from helpers import (make_book, make_ctx, page_align_ref, page_decision,
                     page_match, write_product)
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _confusable_char

BOOK, PAGE, COL, SLOT = "tbook", 1, 1, 7


def _run(tmp_path, monkeypatch, *, cands, verdict="unsure", align=None, params=None):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[
            dict(slot=SLOT, verdict=verdict, cov=cands[0][1], wmax=4.0,
                 char=cands[0][0] if verdict == "same" else None, candidates=cands),
        ]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, char=None, margin=0.01, source="prior")]))
    if align is not None:
        write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
            PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, **align)]))
    ctx.params["seed_admit"] = SeedAdmitParams(**(params or {}))
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    (r,) = col.chars
    return r


SOLO_PLAIN = [("明", 0.996), ("朋", 0.90)]
SOLO_CONF = [("千", 0.996), ("子", 0.85)]      # 千 在形近表里（千/干/子）


def test_fixture_confusable_premise():
    assert _confusable_char("千")
    assert not _confusable_char("明")


def test_solo_default_admits(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=SOLO_PLAIN, verdict="same")
    assert r.admit and r.channel == "match_solo" and r.char == "明"
    r = _run(tmp_path, monkeypatch, cands=SOLO_CONF, verdict="same")
    assert r.admit and r.channel == "match_solo" and r.char == "千"


def test_off_channels_sends_solo_to_review(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=SOLO_PLAIN, verdict="same",
             params={"off_channels": "match_solo"})
    assert not r.admit and r.channel is None
    assert "channel_off" in r.doubts


def test_off_channels_other_channel_untouched(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=SOLO_PLAIN, verdict="same",
             params={"off_channels": "match_replace, match_margin"})
    assert r.admit and r.channel == "match_solo"


def test_solo_confusable_guard(tmp_path, monkeypatch):
    on = {"solo_confusable_guard": True}
    r = _run(tmp_path, monkeypatch, cands=SOLO_CONF, verdict="same", params=on)
    assert not r.admit and "solo_confusable" in r.doubts
    r = _run(tmp_path, monkeypatch, cands=SOLO_PLAIN, verdict="same", params=on)
    assert r.admit and r.channel == "match_solo"


# match_replace：整理本 replace 层给「旣」，库 top1「既」（语义同、字面不同），库 unsure。
# （原例 嚐/嘗：2026-09-28 overview#201 登记进 never_group、语义层不再同义，改用 旣/既）
REPL = dict(cands=[("既", 0.97), ("當", 0.90)], verdict="unsure",
            align={"align_char": "旣", "align_op": "replace"})


def test_replace_default_takes_align_form(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, **REPL)
    assert r.admit and r.channel == "match_replace" and r.char == "旣"


def test_replace_form_lib(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, **REPL, params={"replace_form": "lib"})
    assert r.admit and r.channel == "match_replace" and r.char == "既"


def test_replace_form_review(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, **REPL, params={"replace_form": "review"})
    assert not r.admit and "replace_form" in r.doubts


def test_replace_form_same_literal_untouched(tmp_path, monkeypatch):
    """整理本字与库 top1 字面相同：三个取值结果一样，照放。"""
    for mode in ("align", "lib", "review"):
        r = _run(tmp_path, monkeypatch, cands=[("嘗", 0.97), ("當", 0.90)], verdict="unsure",
                 align={"align_char": "嘗", "align_op": "replace"},
                 params={"replace_form": mode})
        assert r.admit and r.channel == "match_replace" and r.char == "嘗", mode


def test_replace_form_rejects_unknown_value(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        _run(tmp_path, monkeypatch, **REPL, params={"replace_form": "nope"})
