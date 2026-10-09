# -*- coding: utf-8 -*-
"""Step7 `solo_ctx_veto`（2026-10-09，overview#450）：match_solo 系放行前看 context_decide.ranked。

vol05 `147:9:9` 金标士：库候选 土 0.9955／士 0.9813（纯形状），context_decide.ranked 是
士 0.6327／土 0.2218，match_solo 放了土。第一名与放行字**语义不同**且概率 ≥ 门槛就落审；
异体码点差不拦。缺省 0 = 关 = 旧行为，且不进参数 dump（没开的书参数哈希不变）。
"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import (make_book, make_ctx, page_decision, page_match, write_product)
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _solo_ctx_vetoed

BOOK, PAGE, COL, SLOT = "tbook", 1, 1, 7
CANDS = [("土", 0.9955), ("士", 0.9813), ("圡", 0.9733)]
SKIP = {"patch_missing": "skip"}     # unsure 档会去取 CNN 背书的图块，测试里没有图
ON = {**SKIP, "solo_ctx_veto": 0.5}


def _run(tmp_path, monkeypatch, *, ranked, cands=CANDS, params=None):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[
            dict(slot=SLOT, verdict="unsure", cov=cands[0][1], wmax=4.0, char=None,
                 candidates=cands)]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, char=None, margin=0.41, source="prior",
                                        ranked=ranked)]))
    ctx.params["seed_admit"] = SeedAdmitParams(**(params or {}))
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    (r,) = col.chars
    return r


AGAINST = [("士", 0.6327), ("土", 0.2218), ("圡", 0.1092)]
WITH = [("土", 0.7), ("士", 0.2)]
WEAK = [("士", 0.40), ("土", 0.38)]
VARIANT = [("為", 0.9), ("土", 0.05)]      # 為/爲 同语义（异体表）：码位差不算分歧


def test_default_off_admits(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, ranked=AGAINST, params=SKIP)
    assert r.admit and r.channel == "match_solo" and r.char == "土"


def test_context_against_goes_to_review(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, ranked=AGAINST, params=ON)
    assert not r.admit and "solo_ctx_veto" in r.doubts


def test_context_agrees_still_admitted(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, ranked=WITH, params=ON)
    assert r.admit and r.channel == "match_solo" and r.char == "土"


def test_weak_context_below_threshold_admits(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, ranked=WEAK, params=ON)
    assert r.admit and r.channel == "match_solo"


def test_variant_codepoint_not_a_veto(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, ranked=VARIANT, cands=[("爲", 0.9955), ("土", 0.90)], params=ON)
    assert r.admit and r.channel == "match_solo"


def test_no_ranked_untouched(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, ranked=[], params=ON)
    assert r.admit and r.channel == "match_solo"


def test_off_params_dump_unchanged():
    assert "solo_ctx_veto" not in SeedAdmitParams().model_dump()
    assert SeedAdmitParams(solo_ctx_veto=0.5).model_dump()["solo_ctx_veto"] == 0.5


# ── _solo_ctx_vetoed 边界：直接测函数，用最小替身（不走整页流水线）──────

class _Dec:
    def __init__(self, ranked):
        self.ranked = ranked


class _IdMap:
    def semantic(self, ch):
        return ch


class _CollapseMap:
    """把 為／爲 映成同一语义值（模拟异体表并组）。"""
    def semantic(self, ch):
        return "同" if ch in ("為", "爲") else ch


def test_fn_veto_at_threshold_exact():
    # 代码是 >=：概率恰等于门槛也判 veto
    assert _solo_ctx_vetoed(_Dec([("士", 0.5), ("土", 0.3)]), [("土", 0.99)], _IdMap(), 0.5)


def test_fn_no_veto_just_below_threshold():
    assert not _solo_ctx_vetoed(_Dec([("士", 0.4999), ("土", 0.3)]), [("土", 0.99)], _IdMap(), 0.5)


def test_fn_no_veto_without_ranked():
    assert not _solo_ctx_vetoed(_Dec([]), [("土", 0.99)], _IdMap(), 0.5)
    assert not _solo_ctx_vetoed(None, [("土", 0.99)], _IdMap(), 0.5)


def test_fn_no_veto_without_candidates():
    assert not _solo_ctx_vetoed(_Dec([("士", 0.9)]), [], _IdMap(), 0.5)


def test_fn_no_veto_when_top_matches_library_top():
    # ranked 第一名与库 top1 同字（库 top1 按概率取，不看列表次序）
    assert not _solo_ctx_vetoed(_Dec([("土", 0.9), ("士", 0.1)]),
                                [("士", 0.9), ("土", 0.99)], _IdMap(), 0.5)


def test_fn_no_veto_when_semantics_collapse():
    # 码位不同但语义同：不算分歧，即使概率远超门槛
    assert not _solo_ctx_vetoed(_Dec([("為", 0.9)]), [("爲", 0.99)], _CollapseMap(), 0.5)
