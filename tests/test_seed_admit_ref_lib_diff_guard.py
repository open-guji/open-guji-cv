# -*- coding: utf-8 -*-
"""`ref_lib` 在库判 diff 时不放行（A24 2026-10-24）。

殿本 vol06 v0.5.12 重跑实测 149:3:3：图是「也」，框带版框竖线，整理本对位与库 top1 都给「十」，
库判 diff（cov 0.83），`relax_ref_agree` 的 `ref_lib` 分支照旧放成「十」。库已明说「不像」时，
整理本与 top1 一致不能证明刻的是这个字，记 doubt `ref_lib_diff`、退回人审。测试数字与字照抄 `test_seed_admit_ref_lib_variant_guard.py` 的摆法。
"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_match, write_product
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.kinds.recog import AlignRec, PageAlignRef
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL, SLOT = "tbook", 1, 1, 15


def _run(tmp_path, monkeypatch, *, verdict: str, params: dict | None = None):
    ctx = make_ctx(tmp_path, make_book(BOOK, iron_gate=False), monkeypatch=monkeypatch)   # 铁证通道要读字块，这里没摆
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[
            dict(slot=SLOT, verdict=verdict, cov=0.9443, wmax=25.81,
                 candidates=[("變", 0.9443), ("泊", 0.939)]),
        ]))
    # replace 段：equal 段会在 admission_decision 早期通道先放行，测不到 relax_ref_agree
    write_product(ctx, "align_ref", PAGE, align_ref=PageAlignRef(
        page=PAGE, anchored=True,
        chars=[AlignRec(id=f"{BOOK}:{PAGE}:{COL}:{SLOT}", col=COL, slot=SLOT,
                        align_char="變", align_op="replace")]))
    ctx.params["seed_admit"] = SeedAdmitParams(**{"shadow_veto": False, **(params or {})})   # 影子闸要真字形库，这里没摆
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    (r,) = col.chars
    return r


def test_diff_verdict_blocks_ref_lib(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, verdict="diff")
    assert r.admit is False, f"库判 diff 仍被放行：channel={r.channel} char={r.char}"
    assert "ref_lib_diff" in r.doubts, r.doubts


def test_unsure_verdict_still_admitted(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, verdict="unsure")
    assert r.admit is True and r.channel == "ref_lib" and r.char == "變"
    assert "ref_lib_diff" not in r.doubts


def test_guard_default_on_and_switchable(tmp_path, monkeypatch):
    assert SeedAdmitParams().ref_lib_diff_guard is True
    r = _run(tmp_path, monkeypatch, verdict="diff", params={"ref_lib_diff_guard": False})
    assert r.admit is True and r.channel == "ref_lib" and r.char == "變"
