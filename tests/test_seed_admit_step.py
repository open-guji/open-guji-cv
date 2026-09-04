# -*- coding: utf-8 -*-
"""C1 进库准入包壳。

守住 glyph_db_first_design §7.3 的四条原则里跟这一步有关的两条：
OCR 置信度不参与自动判断；库匹配按 cov 分档、0.99 是拐点。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.book import load_book
from open_guji_cv.core.spec import page_key
from open_guji_cv.core.step import KINDS, STEPS
from open_guji_cv.products.store import ProductStore

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data_full" / "zongmu"
needs_raw = pytest.mark.skipif(not RAW.exists(), reason="需要 data_full/zongmu 原图")


def test_registered():
    assert "seed_admit" in STEPS and "seed_admit" in KINDS
    assert "db" in STEPS["seed_admit"].spec.needs


@needs_raw
def test_auto_admissions_always_carry_a_channel_and_a_char():
    """自动进库的必须说清走的哪条通道、进的哪个字——不许有匿名准入。"""
    store = ProductStore()
    seen = 0
    for pg in load_book("vol01").dev_set[:6]:
        d = store.read("vol01", "seed_admit", page_key(pg), "seed_admit")
        if d is None:
            continue
        for cc in d.columns:
            for r in cc.chars:
                if not r.admit:
                    continue
                seen += 1
                assert r.channel, f"{r.id} 自动进库却没有通道名"
                assert r.char, f"{r.id} 自动进库却没有字"
                assert r.provenance in ("match", "context", "align"), \
                    f"{r.id} provenance 不合法：{r.provenance}"
    if not seen:
        pytest.skip("还没跑过 seed_admit")


@needs_raw
def test_match_solo_requires_the_cov_cutoff():
    """match_solo 通道的 cov 必须够 0.99——那是实测拐点，不是拍的。

    库匹配按 cov 分档的准确率：same 100% / ≥0.99 100% / ≥0.98 95.2% /
    ≥0.95 68.5% / <0.95 10.2%（529 条人审回放）。
    """
    store = ProductStore()
    checked = 0
    for pg in load_book("vol01").dev_set[:6]:
        a = store.read("vol01", "seed_admit", page_key(pg), "seed_admit")
        if a is None:
            continue
        for cc in a.columns:
            for r in cc.chars:
                if r.channel != "match_solo":
                    continue
                cov = r.evidence.get("cov", 0.0)
                assert cov >= 0.99, f"{r.id} 走 match_solo 但 cov 只有 {cov}"
                checked += 1
    if not checked:
        pytest.skip("没有 match_solo 记录")


@needs_raw
def test_review_items_say_why():
    """落回人审的要写明疑问——审查页靠它给人看「为什么拿不准」。"""
    store = ProductStore()
    seen = 0
    for pg in load_book("vol01").dev_set[:6]:
        d = store.read("vol01", "seed_admit", page_key(pg), "seed_admit")
        if d is None:
            continue
        for cc in d.columns:
            for r in cc.chars:
                if r.admit:
                    continue
                seen += 1
                assert r.doubts, f"{r.id} 落回人审却没说原因"
    if not seen:
        pytest.skip("这几页全自动了")


@needs_raw
def test_counts_add_up():
    store = ProductStore()
    for pg in load_book("vol01").dev_set[:4]:
        d = store.read("vol01", "seed_admit", page_key(pg), "seed_admit")
        if d is None:
            continue
        n = sum(len(cc.chars) for cc in d.columns if cc.ok)
        assert d.n_auto + d.n_review == n, \
            f"p{pg} 计数对不上：{d.n_auto}+{d.n_review} != {n}"
