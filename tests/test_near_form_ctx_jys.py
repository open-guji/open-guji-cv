# -*- coding: utf-8 -*-
"""己/已/巳 上下文表规则（overview#428，N1）：`utils/near_form_ctx.decide` + `seed_admit.ji_yi_si_ctx_rule`。
表自己造（不依赖 config 里的真表）。"""
from __future__ import annotations

import json

import open_guji_cv.steps  # noqa: F401
import open_guji_cv.utils.near_form_ctx as nfc
from helpers import (make_book, page_align_ref, page_chars, page_match, write_product)
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1


def _table(tmp_path, keys):
    p = tmp_path / "ctx.json"
    p.write_text(json.dumps({"keys": keys}), encoding="utf-8")
    return str(p)


def test_decide_pure_key_decides(tmp_path):
    p = _table(tmp_path, {"11|而|矣": [0, 20, 0]})
    assert nfc.decide("而", "矣", path=p)[0] == "已"


def test_decide_prefers_specific_and_abstains_on_mixed(tmp_path):
    # 更特异的键（2,2）不纯 → 弃权，不往更粗的纯键退
    p = _table(tmp_path, {"22|之而|矣乎": [0, 6, 4], "11|而|矣": [0, 50, 0]})
    ch, why = nfc.decide("之而", "矣乎", path=p)
    assert ch is None and "不纯" in why
    assert nfc.decide("他而", "矣乎", path=p)[0] == "已"      # (2,2) 无键，退到 (1,1)


def test_decide_min_n_and_no_key(tmp_path):
    p = _table(tmp_path, {"11|而|矣": [0, 4, 0]})
    assert nfc.decide("而", "矣", min_n=5, path=p)[0] is None
    assert nfc.decide("山", "水", path=p) == (None, "上下文表无键")


def test_decide_context_too_short(tmp_path):
    p = _table(tmp_path, {"11|而|矣": [0, 9, 0], "01|||矣": [0, 9, 0]})
    assert nfc.decide("", "矣", path=p)[0] is None        # 没有前文，(1,1) 用不了；(0,1) 键不存在


def test_param_default_off():
    assert SeedAdmitParams().ji_yi_si_ctx_rule is False


def _ctx(tmp_path, monkeypatch, params):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    return RunContext(make_book(BOOK), ProductStore(products), ImageCache(cache),
                      params={"seed_admit": params}, log=lambda s: None)


def _run(ctx, left, right, ref):
    recs = [
        dict(slot=1, verdict="same", cov=1.0, wmax=0.0, char=left, candidates=[(left, 1.0)]),
        dict(slot=2, verdict="unsure", cov=0.5, wmax=0.0, candidates=[("巳", 0.5), ("已", 0.4)]),
        dict(slot=3, verdict="same", cov=1.0, wmax=0.0, char=right, candidates=[(right, 1.0)]),
    ]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
        PAGE, BOOK, recs=[dict(slot=1, align_char=left), dict(slot=2, align_char=ref),
                          dict(slot=3, align_char=right)], col=COL))
    sa = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    return {r.slot: r for cc in sa.columns for r in cc.chars}[2]


def test_rule_on_admits_when_table_decides_and_ignores_ref(tmp_path, monkeypatch):
    monkeypatch.setattr(nfc, "CONFIG", tmp_path / "ctx.json")
    _table(tmp_path, {"11|而|矣": [0, 30, 0]})
    ctx = _ctx(tmp_path, monkeypatch, SeedAdmitParams(ji_yi_si_ctx_rule=True))
    r = _run(ctx, "而", "矣", ref="巳")     # 整理本给「巳」，表说「已」：以表为准
    assert r.admit and r.char == "已" and r.channel == "ji_yi_si"
    assert "上下文表" in r.evidence["ji_yi_si"]["why"]


def test_rule_on_sends_to_review_when_table_silent(tmp_path, monkeypatch):
    monkeypatch.setattr(nfc, "CONFIG", tmp_path / "ctx.json")
    _table(tmp_path, {"11|而|矣": [0, 30, 0]})
    ctx = _ctx(tmp_path, monkeypatch, SeedAdmitParams(ji_yi_si_ctx_rule=True))
    r = _run(ctx, "山", "水", ref="巳")
    assert not r.admit and "ji_yi_si_ctx_review" in r.doubts


def test_rule_off_keeps_old_behavior(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, SeedAdmitParams())
    r = _run(ctx, "山", "水", ref="巳")
    assert r.admit and r.char == "巳"          # 同 test_seed_admit_ji_yi_si_0927 的老行为
