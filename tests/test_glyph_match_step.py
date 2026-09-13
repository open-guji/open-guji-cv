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


def _ws_raw():
    """原图根：优先 GUJI_WORKSPACE（数据已迁 siku-zongmu-workspace），
    没设则退回仓根——引擎自带的小样本仍在仓内。"""
    from open_guji_cv.core.workspace import raw_root
    return raw_root()
RAW = _ws_raw() / "data_full" / "zongmu"
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
    """换一个库指纹，产物指纹必须跟着变——这是 stale 传播的唯一依据。

    ⚠️ **不能断言「当前是 fresh」**：库是活的，人裁一进库指纹就变、这一步
    立刻转 stale（2026-09-04 实测：用户 82 条定字进库后 p24 就是 stale——
    那正是这个机制在正常工作）。所以直接比两个指纹，不看当前状态。
    """
    store = ProductStore()
    if store.read_raw("vol01", "glyph_match", page_key(24)) is None:
        pytest.skip("vol01/24 还没跑过 glyph_match")
    bk, pl = load_book("vol01"), load_pipeline("keben_body_v2")
    eng = Engine(bk, pl, store, ImageCache())
    step = STEPS["glyph_match"]

    eng.ctx.params["glyph_match"] = GlyphMatchParams(db_fingerprint="aaaa")
    fp_a, _, _ = eng.fingerprint(step, 24)
    eng.ctx.params["glyph_match"] = GlyphMatchParams(db_fingerprint="bbbb")
    fp_b, _, _ = eng.fingerprint(step, 24)
    assert fp_a and fp_b and fp_a != fp_b, "库指纹变了，Step 指纹却没变"

    # 且指纹对不上时状态必须是 stale（而不是 fresh/missing）
    st = eng.status(pages=[24])["steps"]["glyph_match"]["pages"][24]["status"]
    assert st in ("stale", "fresh"), f"意外状态 {st}"


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


def test_diff_verdict_still_reports_best_candidate():
    """diff 档要带出「最像的那个字」——判决不变，只补证据。

    2026-09-12：Step7 切分裁决的卡片上大量显示「? 99%」——cov 明明 0.99，
    却连它像哪个字都不说，人没法拿这个信息裁切法。根因是 `GlyphMatcher.match`
    在逐对 verify 全判 diff 时 `unsure_best` 为空，返回的 `candidates` 也空，
    只剩一个 `best_cov` 数字。实测 vol02 那批待裁切线：空候选池的 2702 个
    候选变体里 p50 cov=0.984、810 个 ≥0.99，全是 `verify.py` 的
    「cov≥0.996 **且** wmax≤12」里 cov 够而 wmax 超标（形近护栏）掉下来的。

    ⚠️ 断言必须同时钉住「判决没变」：verdict 仍 diff、char 仍 None。
    带候选是给人和自动判据看的证据，不是"库认了这个字"——一旦 char 被填上，
    seed_admit 会把它当认出来的字直接收，那是另一个量级的错。
    """
    import numpy as np
    from dataclasses import dataclass

    from open_guji_cv.clustering.match import GlyphMatcher

    @dataclass
    class _V:
        verdict: str
        f1: float
        diff_blob_ratio: float

    m = GlyphMatcher.__new__(GlyphMatcher)
    m._ids, m._chars = ["a", "b"], ["傅", "則"]
    m._patches = [np.zeros((8, 8), np.uint8)] * 2
    m._feats = np.eye(2, dtype=np.float32)
    m._feature = type("F", (), {"extract": staticmethod(
        lambda x: np.array([[1.0, 0.0]], dtype=np.float32))})()
    m.k, m.cov_high, m.miss_wmax = 2, 0.996, 12
    m.guard_needs_partner_in_db, m._char_set = False, {"傅", "則"}

    # 两对都判 diff（wmax 超标），best 是 傅@0.991
    seq = iter([("diff", 0.991), ("diff", 0.930)])
    m._verify = lambda a, b, cov_high=None, miss_wmax=None: _V(*next(seq), 20.0)

    r = m.match(np.zeros((8, 8), np.uint8))
    assert r.verdict == "diff", "判决不该变"
    assert r.char is None, "diff 档绝不能填 char——下游会当成认出来的字直接收"
    assert r.candidates == [("傅", 0.991)], f"该带出最像的字，实际 {r.candidates}"

    # 库空 / 摘掉自身后没剩候选：候选池本就该是空的，不能硬塞
    empty = GlyphMatcher.__new__(GlyphMatcher)
    empty._ids = []
    assert empty.match(np.zeros((8, 8), np.uint8)).candidates == []
