# -*- coding: utf-8 -*-
"""Step5 库匹配包壳（阶段 B1）。

最关键的一条：**库是外部状态，必须进指纹**。库长大或条目改判之后，同一张
图块的判决会变，而代码/参数/上游产物一个都没动——指纹不带库，产物就永远
显示 fresh、拿着过期判决往下走。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.book import load_book
from open_guji_cv.core.engine import Engine, params_hash
from open_guji_cv.core.pipeline import load_pipeline
from open_guji_cv.core.spec import page_key
from open_guji_cv.core.step import KINDS, STEPS
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.glyph_match import GlyphMatchParams, db_fingerprint

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data_full" / "zongmu"
needs_raw = pytest.mark.skipif(not RAW.exists(), reason="需要 data_full/zongmu 原图")


def test_step_and_kinds_are_registered():
    assert "glyph_match" in STEPS
    assert "glyph_match" in KINDS and "ocr_candidates" in KINDS


def test_db_fingerprint_lands_in_params_automatically():
    """留空的 db_fingerprint 要在构造时自动填——不填就等于没进指纹。"""
    p = GlyphMatchParams()
    assert p.db_fingerprint, "指纹没自动填充"
    assert p.db_fingerprint == db_fingerprint(p.db_path)


def test_params_hash_changes_when_the_library_changes():
    """库指纹一变，参数哈希必须跟着变——这是 stale 传播的唯一依据。"""
    a = GlyphMatchParams(db_fingerprint="aaaa")
    b = GlyphMatchParams(db_fingerprint="bbbb")
    assert params_hash(a) != params_hash(b)


def test_missing_db_does_not_crash_fingerprint():
    assert db_fingerprint("no/such/glyph.db") == "nodb"


@needs_raw
def test_stale_propagates_when_library_fingerprint_changes():
    """换一个库指纹，已落盘的产物要立刻标 stale。"""
    store = ProductStore()
    if store.read_raw("vol01", "glyph_match", page_key(24)) is None:
        pytest.skip("vol01/24 还没跑过 glyph_match")
    bk, pl = load_book("vol01"), load_pipeline("keben_body_v2")
    eng = Engine(bk, pl, store, ImageCache())
    assert eng.status(pages=[24])["steps"]["glyph_match"]["pages"][24]["status"] == "fresh"
    eng.ctx.params["glyph_match"] = GlyphMatchParams(db_fingerprint="deadbeef")
    assert eng.status(pages=[24])["steps"]["glyph_match"]["pages"][24]["status"] == "stale"


@needs_raw
def test_products_carry_per_instance_evidence():
    """逐实例证据（设计 §3 纪律 1）：same 档必须留下命中的库条目与 cov。"""
    store = ProductStore()
    d = store.read("vol01", "glyph_match", page_key(24), "glyph_match")
    if d is None:
        pytest.skip("还没跑过")
    same = [r for cc in d.columns for r in cc.chars if r.verdict == "same"]
    assert same, "一个 same 都没有，库或图块有问题"
    for r in same[:20]:
        assert r.char and r.matched_id, f"{r.id} same 档却没留证据"
        assert r.cov >= 0.99, f"{r.id} same 档 cov 只有 {r.cov}"
    assert d.db_fingerprint, "产物没记下判决是对哪个库做的"
