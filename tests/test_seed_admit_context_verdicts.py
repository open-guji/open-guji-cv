# -*- coding: utf-8 -*-
"""Step7 `context` 通道按库 verdict 加闸（2026-09-27，D-书级admit覆盖）。

依据全唐文放行抽检（overview `新书整理/书/全唐文/放行抽检-v0.md`）：独立两次
抽样都测到 `channel=context ∧ verdict=diff` 错率约 50%（n=40），按锚定/未锚定
拆开复核过、错率不随锚定与否变化——问题在 `verdict=diff` 这个组合本身，
`context_margin` 顶格覆盖这条视觉证据不可靠。`context_verdicts` 参数让书级配置
挡住指定 verdict 的 context 放行,不在允许集合里的记 doubt `context_verdict`。
"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_decision, page_match, write_product
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL, SLOT = "tbook", 1, 1, 15


def _run(tmp_path, monkeypatch, *, verdict: str, params: dict | None = None):
    """摆一格「库判 `verdict`（弱证据、不足以自动放行）+ Step6 上下文定字 X、
    margin 过线」的证据，不给 `align_ref`（align_char=None，隔离
    `context_vs_ref` 互证闸，只测 verdict 闸本身）。"""
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[
            dict(slot=SLOT, verdict=verdict, cov=0.50, wmax=10.0,
                 candidates=[("某", 0.50)]),
        ]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[
            dict(slot=SLOT, char="X", margin=0.90, source="context"),
        ]))
    # 单格列里这格就是列首；列首非字护栏（D274）不是本文件要测的，关掉隔离
    ctx.params["seed_admit"] = SeedAdmitParams(**{"context_head_check": False, **(params or {})})
    return STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]


def _rec(sa):
    (col,) = sa.columns
    (r,) = col.chars
    return r


def test_default_empty_allows_all_verdicts_diff(tmp_path, monkeypatch):
    """默认 `context_verdicts=""`（不限制）：`verdict=diff` 仍照旧放行——
    加这个参数前后，没配置的书行为逐字节不变。"""
    r = _rec(_run(tmp_path, monkeypatch, verdict="diff"))
    assert r.admit is True and r.channel == "context" and r.char == "X"


def test_default_empty_allows_all_verdicts_unsure(tmp_path, monkeypatch):
    r = _rec(_run(tmp_path, monkeypatch, verdict="unsure"))
    assert r.admit is True and r.channel == "context" and r.char == "X"


def test_diff_excluded_falls_to_review(tmp_path, monkeypatch):
    """书配 `context_verdicts="same,unsure"`：`verdict=diff` 不再放行，落人审、
    记 doubt `context_verdict`。"""
    r = _rec(_run(tmp_path, monkeypatch, verdict="diff",
                  params={"context_verdicts": "same,unsure"}))
    assert r.admit is False, f"diff 未被挡住：channel={r.channel}"
    assert "context_verdict" in r.doubts
    assert r.channel != "context"


def test_unsure_still_allowed_when_only_diff_excluded(tmp_path, monkeypatch):
    """挡 diff 不误伤 unsure——`same,unsure` 这个允许集合里 unsure 照放。"""
    r = _rec(_run(tmp_path, monkeypatch, verdict="unsure",
                  params={"context_verdicts": "same,unsure"}))
    assert r.admit is True and r.channel == "context" and r.char == "X"
    assert "context_verdict" not in r.doubts


def test_use_context_false_still_wins_over_verdict_gate(tmp_path, monkeypatch):
    """`use_context=false`（全关）时整条 context 通道都不生效，`context_verdicts`
    配了也不影响这个更粗的开关——两个参数各管各的，互不覆盖。"""
    r = _rec(_run(tmp_path, monkeypatch, verdict="same",
                  params={"use_context": False, "context_verdicts": "same"}))
    assert r.admit is False
    assert r.channel != "context"
    assert "context_verdict" not in r.doubts


def test_whitespace_and_trailing_comma_are_tolerated(tmp_path, monkeypatch):
    """人手写 yaml 常带多余空格/逗号，解析要容错（同 `always_review`/
    `exclusion_origins` 现有写法）。"""
    r = _rec(_run(tmp_path, monkeypatch, verdict="unsure",
                  params={"context_verdicts": " same, unsure ,"}))
    assert r.admit is True and r.channel == "context"
