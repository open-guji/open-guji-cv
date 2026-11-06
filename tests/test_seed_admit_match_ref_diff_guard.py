# -*- coding: utf-8 -*-
"""`match_ref` 在库判 diff 时不放行，书级开关 `match_ref_diff_guard`，缺省关（A24 2026-11-06）。

殿本 vol05 66:9:15：图上是「不」，对位滑格给「字」，库首选也是「字」但库判 diff，
match_ref（equal 段）没有 cov／verdict 下限，照旧放成「字」。开关打开后记 doubt `match_ref_diff`、退回人审。
摆法照抄 `test_seed_admit_ref_lib_diff_guard.py`，对位改 equal 段，字换成没有异写组的「字」（變有 變𠮓 组要读字块）。
"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_match, write_product
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.kinds.recog import AlignRec, PageAlignRef
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL, SLOT = "tbook", 1, 1, 15


def _run(tmp_path, monkeypatch, *, verdict: str, params: dict | None = None):
    ctx = make_ctx(tmp_path, make_book(BOOK, iron_gate=False), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[
            dict(slot=SLOT, verdict=verdict, cov=0.9443, wmax=25.81,
                 candidates=[("字", 0.9443), ("宇", 0.90)]),
        ]))
    write_product(ctx, "align_ref", PAGE, align_ref=PageAlignRef(
        page=PAGE, anchored=True,
        chars=[AlignRec(id=f"{BOOK}:{PAGE}:{COL}:{SLOT}", col=COL, slot=SLOT,
                        align_char="字", align_op="equal")]))
    ctx.params["seed_admit"] = SeedAdmitParams(**{"shadow_veto": False, "group_flow": ("jys",), **(params or {})})
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    (r,) = col.chars
    return r


def test_default_off_still_admits_diff(tmp_path, monkeypatch):
    assert SeedAdmitParams().match_ref_diff_guard is False
    r = _run(tmp_path, monkeypatch, verdict="diff")
    assert r.admit is True and r.channel == "match_ref" and r.char == "字"


def test_on_blocks_diff(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, verdict="diff", params={"match_ref_diff_guard": True})
    assert r.admit is False, f"库判 diff 仍被放行：channel={r.channel} char={r.char}"
    assert "match_ref_diff" in r.doubts, r.doubts


def test_on_keeps_unsure(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, verdict="unsure", params={"match_ref_diff_guard": True})
    assert r.admit is True and r.channel == "match_ref" and r.char == "字"
    assert "match_ref_diff" not in r.doubts


def test_dump_and_lane_hard():
    from open_guji_cv.steps.seed_admit import _LANE_HARD
    assert "match_ref_diff_guard" not in SeedAdmitParams().model_dump()      # 缺省关不进 dump，产物不过期
    assert SeedAdmitParams(match_ref_diff_guard=True).model_dump()["match_ref_diff_guard"] is True
    assert "match_ref_diff" in _LANE_HARD
