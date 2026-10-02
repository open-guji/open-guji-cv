# -*- coding: utf-8 -*-
"""Step7 context 通道护栏（`context_guard_*`，overview#333，G1 道）。

四种放错形态：界行杆／切坏格带标记（vol03:110:7:3、94:9:2）、库判 diff 且 cov 低
（vol03:48:8:21）、整理本坐标对位说是空格（vol03:110:5:1）、整理本有字而 context 另定一字。
数据全是自造的产物，不碰真书。"""
from __future__ import annotations

import json

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, page_chars, page_decision, page_match, write_product
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.kinds.recog import CoordRec, PageAlignRef
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1


def _ctx(tmp_path, monkeypatch, **params):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    kwargs = {"seed_admit": SeedAdmitParams(**params)} if params else {}
    return RunContext(make_book(BOOK), ProductStore(products), ImageCache(cache),
                      params=kwargs, log=lambda s: None)


def _run(ctx, *, verdict="unsure", cov=0.86, flags=None, ref=None, ctx_char="今"):
    """一格：库不定（没有任何字形通道能放行）、context 定了 `ctx_char`。`ref` 给坐标对位字
    （空串 = 空格位；None = 没有坐标记录）。"""
    write_product(ctx, "glyph_match", PAGE,
                  glyph_match=page_match(PAGE, BOOK, col=COL, recs=[
                      dict(slot=1, verdict=verdict, cov=cov, wmax=0.0, candidates=[])]))
    write_product(ctx, "context_decide", PAGE,
                  context_decision=page_decision(PAGE, BOOK, col=COL, recs=[
                      dict(slot=1, char=ctx_char, margin=0.9, source="context")]))
    write_product(ctx, "cell_shrink", PAGE,
                  char_index=page_chars(PAGE, BOOK, col=COL, recs=[
                      dict(slot=1, ink_ratio=0.3, flags=flags or [])]))
    coord = ([CoordRec(id=f"{BOOK}:{PAGE}:{COL}:1", col=COL, slot=1, ref_char=ref)]
             if ref is not None else [])
    write_product(ctx, "align_ref", PAGE,
                  align_ref=PageAlignRef(page=PAGE, anchored=False, coord=coord, coord_cols=[COL]))
    sa = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    return [r for cc in sa.columns for r in cc.chars][0]


def test_baseline_admits_all_four_shapes(tmp_path, monkeypatch):
    """前提：关着护栏时，下面四种格都被 context 通道放行——否则后面的拦截测试是空转。"""
    cases = [dict(verdict="diff", cov=0.78), dict(flags=["rule_bar"]),
             dict(ref=""), dict(ref="五", ctx_char="聖")]
    for i, kw in enumerate(cases):
        r = _run(_ctx(tmp_path / str(i), monkeypatch), **kw)
        assert r.admit and r.channel == "context", f"{kw}: {r.channel}/{r.doubts}"


def test_diff_low_cov_blocked(tmp_path, monkeypatch):
    kw = dict(verdict="diff", cov=0.78)
    r = _run(_ctx(tmp_path, monkeypatch, context_guard_diff=True), **kw)
    assert not r.admit and "ctx_guard_diff" in r.doubts
    # cov 过线（≥0.8）的 diff 不拦；unsure 低 cov 也不拦
    r = _run(_ctx(tmp_path / "b", monkeypatch, context_guard_diff=True), verdict="diff", cov=0.85)
    assert r.admit and r.channel == "context"
    r = _run(_ctx(tmp_path / "c", monkeypatch, context_guard_diff=True), verdict="unsure", cov=0.5)
    assert r.admit and r.channel == "context"


def test_flags_blocked_only_for_listed_flags(tmp_path, monkeypatch):
    for fl in ("rule_bar", "suspect_empty", "bad_seg"):
        r = _run(_ctx(tmp_path / fl, monkeypatch, context_guard_flags=True), flags=["boundary_ink", fl])
        assert not r.admit and "ctx_guard_flag" in r.doubts, fl
    # boundary_ink 在 vol03 到处都有（p110 字格大半带它），不在名单里不能拦
    r = _run(_ctx(tmp_path / "ok", monkeypatch, context_guard_flags=True), flags=["boundary_ink", "edge_blob"])
    assert r.admit and r.channel == "context"


def test_ref_blank_blocked_unless_glyph_same(tmp_path, monkeypatch):
    r = _run(_ctx(tmp_path, monkeypatch, context_guard_ref_blank=True), ref="")
    assert not r.admit and r.char is None and "ctx_guard_ref_blank" in r.doubts
    # 没有坐标记录 → 弃权；坐标给了字（非空格）→ 本条不管
    r = _run(_ctx(tmp_path / "b", monkeypatch, context_guard_ref_blank=True), ref=None)
    assert r.admit
    r = _run(_ctx(tmp_path / "c", monkeypatch, context_guard_ref_blank=True), ref="今")
    assert r.admit


def test_ref_prefer_defaults_to_ref_char_and_reviews(tmp_path, monkeypatch):
    r = _run(_ctx(tmp_path, monkeypatch, context_guard_ref_prefer=True), ref="五", ctx_char="聖")
    assert not r.admit and r.char == "五" and "ctx_guard_ref" in r.doubts
    # 整理本与 context 同字：不拦（走原通道）
    r = _run(_ctx(tmp_path / "b", monkeypatch, context_guard_ref_prefer=True), ref="今", ctx_char="今")
    assert r.admit
    # 〓（码表外占位）弃权
    r = _run(_ctx(tmp_path / "c", monkeypatch, context_guard_ref_prefer=True), ref="〓", ctx_char="聖")
    assert r.admit


def test_guard_off_params_dump_unchanged():
    """全关时五个字段都不进 dump（`params_hash` 与加字段前逐位相同）；开任一个才进。"""
    off = SeedAdmitParams(db_path="x").model_dump()
    assert not [k for k in off if k.startswith("context_guard")]
    on = SeedAdmitParams(db_path="x", context_guard_flags=True).model_dump()
    assert on["context_guard_flags"] is True and on["context_guard_cov"] == 0.8
    json.dumps(off)
