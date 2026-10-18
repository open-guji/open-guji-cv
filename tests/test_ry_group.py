# -*- coding: utf-8 -*-
"""日／曰 v2 答案表（overview#441，Z-jys）：`utils/ry_group` + `seed_admit.ry_group`。自造数据。"""
from __future__ import annotations

import json

import open_guji_cv.steps  # noqa: F401
import open_guji_cv.utils.ry_group as ry
from helpers import make_book, page_align_ref, page_match, write_product
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.seed_admit import SeedAdmitParams
from open_guji_cv.utils.ji_yi_si_clf import ctx_key

BOOK, PAGE, COL = "tbook", 1, 1
CID = "tbook:1:1:2"


def _v(muse=("日", "日"), gemini=("日", "日"), haiku=("日",)):
    return {"muse": list(muse), "gemini": list(gemini), "haiku": list(haiku)}


def _cache(tmp_path, cells):
    p = tmp_path / "ry.json"
    p.write_text(json.dumps({"cells": cells}), encoding="utf-8")
    ry._load.cache_clear()
    return str(p)


def _e(votes, ctx=None, ver="ry-v2"):
    return {"ctx": ctx or ctx_key("山", "水"), "ver": ver, "votes": votes}


def test_decide_cases(tmp_path):
    t = _cache(tmp_path, {
        "ok": _e(_v()),
        "ab": _e(_v(gemini=("日", "不确定"))),
        "dis": _e(_v(gemini=("曰", "曰"))),
        "unstable": _e(_v(muse=("日", "曰"))),
        "veto": _e(_v(haiku=("曰",))),
        "hk_abstain": _e(_v(haiku=("不确定",))),
        "ctx": _e(_v(), ctx="xxxx"),
        "ver": _e(_v(), ver="old")})
    d = lambda c: ry.decide(t, c, "山", "水")
    assert d("ok")["char"] == "日" and d("hk_abstain")["char"] == "日"
    assert d("ab")["why"] == "abstain:gemini" and d("ab")["char"] is None
    assert d("dis")["why"] == "disagree" and d("unstable")["why"] == "disagree"
    assert d("veto")["why"] == "haiku_veto"
    assert d("ctx")["why"] == "ctx_mismatch" and d("ver")["why"] == "ver_mismatch"
    assert d("zz") == {"char": None, "why": "cache_miss"}
    assert ry.decide("", "ok", "山", "水") is None


def _ctx(tmp_path, monkeypatch, params):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    return RunContext(make_book(BOOK), ProductStore(products), ImageCache(cache),
                      params={"seed_admit": params}, log=lambda s: None)


def _run(ctx, ref="日"):
    recs = [
        dict(slot=1, verdict="same", cov=1.0, wmax=0.0, char="山", candidates=[("山", 1.0)]),
        dict(slot=2, verdict="unsure", cov=0.5, wmax=0.0, candidates=[("木", 0.5), ("本", 0.4)]),
        dict(slot=3, verdict="same", cov=1.0, wmax=0.0, char="水", candidates=[("水", 1.0)]),
    ]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
        PAGE, BOOK, recs=[dict(slot=1, align_char="山"), dict(slot=2, align_char=ref),
                          dict(slot=3, align_char="水")], col=COL))
    sa = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    return {r.slot: r for cc in sa.columns for r in cc.chars}[2]


