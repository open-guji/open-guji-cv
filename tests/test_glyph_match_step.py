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


def test_step_and_kinds_are_registered():
    assert "glyph_match" in STEPS
    assert "glyph_match" in KINDS and "ocr_candidates" in KINDS


def test_db_fingerprint_lands_in_params_automatically():
    """留空的 db_fingerprint 要在构造时自动填——不填就等于没进指纹。"""
    p = GlyphMatchParams()
    assert p.db_fingerprint, "指纹没自动填充"
    assert p.db_fingerprint == db_fingerprint(p.db_path)


def test_library_fingerprint_is_soft_in_params_hash():
    """库指纹是软参数（2026-09-25）：按 Step 的 `soft_params` 算的参数哈希不随库变，
    不剔的全量哈希照旧会变（剔的是这一个字段，不是别的）。"""
    soft = STEPS["glyph_match"].spec.soft_params
    assert soft == ("db_fingerprint",)
    a = GlyphMatchParams(db_fingerprint="aaaa")
    b = GlyphMatchParams(db_fingerprint="bbbb")
    assert params_hash(a, soft) == params_hash(b, soft)
    assert params_hash(a) != params_hash(b)
    c = GlyphMatchParams(db_fingerprint="aaaa", knn_k=7)
    assert params_hash(a, soft) != params_hash(c, soft)


def test_missing_db_does_not_crash_fingerprint():
    assert db_fingerprint("no/such/glyph.db") == "nodb"


def test_library_change_does_not_stale_but_is_reported_as_drift(tmp_path, monkeypatch, ws,
                                                                fixture_page):
    """库指纹变了：Step 指纹**不变**（不判过期），`status` 在 `drift` 里报出来
    （2026-09-25 用户定：库进几个新字形不该让全书 Step5-a 重跑）。

    拿冻结样页把上游产物现跑出来，再用固定库指纹跑一遍 glyph_match 落 manifest。
    """
    import open_guji_cv.steps  # noqa: F401
    from dataclasses import dataclass
    from helpers import run_keben_from_raw
    from open_guji_cv.clustering.match import MatchResult

    @dataclass
    class _StubMatcher:
        def match(self, img, exclude_id=None):
            return MatchResult(verdict="diff", char=None, matched_id=None, cov=0.5,
                               wmax=30.0, candidates=[], n_verified=0)

    bk = load_book("keben")
    ctx, _ = run_keben_from_raw(tmp_path, monkeypatch, book=bk, gray=fixture_page)
    eng = Engine(bk, load_pipeline("keben_body_v2"), ctx.store, ctx.cache)
    step = STEPS["glyph_match"]
    monkeypatch.setattr(type(step), "_matcher", lambda self, p: _StubMatcher())

    eng.ctx.params["glyph_match"] = GlyphMatchParams(db_fingerprint="aaaa")
    fp_a, _, _ = eng.fingerprint(step, 1)
    eng.run(steps=["glyph_match"], pages=[1])
    assert eng.store.manifest(bk.id, "glyph_match").get("p0001").soft == {"db_fingerprint": "aaaa"}
    row = eng.status(pages=[1], steps=["glyph_match"])["steps"]["glyph_match"]
    assert row["drift"] == 0
    before = row["pages"][1]["status"]     # 样页的上游闸不一定全新鲜，只比前后

    eng.ctx.params["glyph_match"] = GlyphMatchParams(db_fingerprint="bbbb")
    fp_b, _, _ = eng.fingerprint(step, 1)
    assert fp_a and fp_a == fp_b, "库指纹变了，Step 指纹不该跟着变（软参数）"
    row = eng.status(pages=[1], steps=["glyph_match"])["steps"]["glyph_match"]
    assert row["pages"][1]["status"] == before and row["drift"] == 1


def test_products_carry_per_instance_evidence(tmp_path, monkeypatch, ws, fixture_page):
    """逐实例证据（设计 §3 纪律 1）：same 档必须留下命中的库条目与 cov，
    产物还要记下判决是对**哪个库**做的。

    2026-09-20：原先读工作区里 vol01/24 跑出来的产物，没跑过就 skip——于是
    这条常年不执行，而它守的是这一步的核心纪律。现在拿冻结样页跑真的
    Step1→Step4 出字块，再把**匹配器**换成一个固定返回 same 的桩：这条要钉的
    是「记录里有没有留证据」，跟库里恰好有没有这个字无关，用真库反而把两件
    事绑在一起（库一变测试就红，红了还说不清是谁的问题）。
    """
    from dataclasses import dataclass

    import open_guji_cv.steps  # noqa: F401
    from helpers import run_keben_from_raw
    from open_guji_cv.clustering.match import MatchResult

    @dataclass
    class _StubMatcher:
        def match(self, img, exclude_id=None):
            return MatchResult(verdict="same", char="甲", matched_id="v2:lib:1:1:1",
                               cov=0.997, wmax=3.0, candidates=[("甲", 0.997)],
                               n_verified=1)

    bk = load_book("keben")
    ctx, _ = run_keben_from_raw(tmp_path, monkeypatch, book=bk, gray=fixture_page)
    step = STEPS["glyph_match"]
    monkeypatch.setattr(type(step), "_matcher", lambda self, p: _StubMatcher())
    ctx.params["glyph_match"] = GlyphMatchParams(db_fingerprint="testfp")

    d = step.run_page(ctx, 1)["glyph_match"]
    same = [r for cc in d.columns for r in cc.chars if r.verdict == "same"]
    assert same, "一个 same 都没有——字块没切出来还是记录没落？"
    for r in same:
        assert r.char and r.matched_id, f"{r.id} same 档却没留证据"
        assert r.cov >= 0.99, f"{r.id} same 档 cov 只有 {r.cov}"
    assert d.db_fingerprint == "testfp", "产物没记下判决是对哪个库做的"


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
