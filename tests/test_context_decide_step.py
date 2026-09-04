# -*- coding: utf-8 -*-
"""Step6 上下文裁决包壳（阶段 B1）。

守两条铁律（context_step 模块头写死的，换任何模型都不许破）：
字形层不可改写（只在候选内重排）、门槛化不做全局重排（拿不准就弃权）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.engine import params_hash
from open_guji_cv.core.spec import page_key
from open_guji_cv.core.step import KINDS, STEPS
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.context_decide import ContextDecideParams, corpus_fingerprint

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data_full" / "zongmu"
needs_raw = pytest.mark.skipif(not RAW.exists(), reason="需要 data_full/zongmu 原图")


def test_registered_and_declares_corpus_need():
    assert "context_decide" in STEPS and "context_decision" in KINDS
    assert "corpus" in STEPS["context_decide"].spec.needs


def test_corpus_fingerprint_lands_in_params_and_moves_the_hash():
    """语料换了同一批候选的裁决就会变——指纹必须进参数、进哈希。"""
    p = ContextDecideParams()
    assert p.corpus_fingerprint
    a = ContextDecideParams(corpus_fingerprint="aaaa")
    b = ContextDecideParams(corpus_fingerprint="bbbb")
    assert params_hash(a) != params_hash(b)
    assert corpus_fingerprint([]) == "nocorpus"


@needs_raw
def test_same_tier_is_inherited_not_rearranged():
    """库 same 档必须原样继承。

    库匹配的 match_precision 是 ≥0.999 的硬约束，让 LM 去重排它只会净亏
    ——1681 槽位实测无条件重排在任何 λ 下都是负的（λ=0.95 仍救 17/坏 34）。
    """
    store = ProductStore()
    m = store.read("vol01", "glyph_match", page_key(24), "glyph_match")
    d = store.read("vol01", "context_decide", page_key(24), "context_decision")
    if m is None or d is None:
        pytest.skip("还没跑过")
    dmap = {r.id: r for cc in d.columns for r in cc.chars}
    checked = 0
    for cc in m.columns:
        for r in cc.chars:
            if r.verdict != "same" or not r.char:
                continue
            dec = dmap.get(r.id)
            assert dec is not None, f"{r.id} 在决策产物里丢了"
            assert dec.char == r.char, \
                f"{r.id} 库判 {r.char}，裁决改成了 {dec.char}——字形层被改写了"
            assert dec.source == "db_same"
            checked += 1
    assert checked, "一个 same 档都没有"


@needs_raw
def test_low_margin_abstains_instead_of_guessing():
    """门槛化：margin 不过阈就弃权（char=None），不硬猜。"""
    store = ProductStore()
    d = store.read("vol01", "context_decide", page_key(24), "context_decision")
    if d is None:
        pytest.skip("还没跑过")
    gate = ContextDecideParams().margin_gate
    for cc in d.columns:
        for r in cc.chars:
            if r.source == "context":
                assert r.char and r.margin >= gate, \
                    f"{r.id} 报了 context 却没过阈：margin={r.margin}"
            if r.source == "prior":
                assert r.char is None, f"{r.id} 没过阈却给了字 {r.char}"


@needs_raw
def test_decided_text_reads_as_continuous_prose():
    """端到端产出的列文本要读得通——这是六步全链的唯一整体验收。"""
    store = ProductStore()
    d = store.read("vol01", "context_decide", page_key(24), "context_decision")
    if d is None:
        pytest.skip("还没跑过")
    cc = d.column(1)
    assert cc is not None
    text = "".join(r.char or "" for r in sorted(cc.chars, key=lambda x: x.slot))
    # p24 c1 是上谕正文；不写死全文（切分一改就漂），只钉住几个高置信锚点
    for anchor in ("文華殿", "文淵"):
        assert anchor in text, f"c1 读出来是「{text}」，缺锚点 {anchor}"
