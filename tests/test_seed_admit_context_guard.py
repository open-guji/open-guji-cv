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
    # 乱码护栏（overview#427，缺省开）会拦这里自造的低 cov 无证人格，本文件只测 G1 四条
    params.setdefault("context_garble_guard", False)
    params.setdefault("context_page_end_review", False)  # 单列自造格即页末格
    kwargs = {"seed_admit": SeedAdmitParams(**params)}
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
    """全关时附属字段不进 dump；diff／ref_blank／ref_prefer 已缺省开，全关是显式选择，三个 False 留在 dump
    里（读回来仍是关）。开任一个时全部进。"""
    off = SeedAdmitParams(db_path="x").model_dump()     # 模块级夹具把三个缺省开的都设成关
    assert sorted(k for k in off if k.startswith("context_guard")) == [
        "context_guard_diff", "context_guard_ref_blank", "context_guard_ref_prefer"]
    assert not any(off[k] for k in off if k.startswith("context_guard"))
    on = SeedAdmitParams(db_path="x", context_guard_diff=True).model_dump()
    assert on["context_guard_diff"] is True and on["context_guard_cov"] == 0.8
    json.dumps(off)


import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")   # 老测试按「放行开关缺省全关」造的数据，见 conftest
