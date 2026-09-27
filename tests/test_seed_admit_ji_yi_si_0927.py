# -*- coding: utf-8 -*-
"""Step7 己/已/巳 一族（2026-09-27 D 铁证复核）：`resolve()` 改 `use_ref="all"`
+ `ji_yi_si_review` 三方一致闸。vol01/vol03/vol04 独立全量穷举都发现「其余→已」
默认规则系统性判偏（vol03 47 格错 55.3%、vol04 34 处、vol01 用 all 模式
45.9%→97.3%），见 `scripts/audit_ji_yi_si_0927.py` 与 `seed_admit._resolve_ji_yi_si`
文档字符串。"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import (make_book, page_align_ref, page_chars, page_decision, page_match,
                     write_product)
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1


def _ctx(tmp_path, monkeypatch, *, params: SeedAdmitParams | None = None):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    kwargs = {"seed_admit": params} if params is not None else {}
    return RunContext(make_book(BOOK), ProductStore(products), ImageCache(cache),
                      params=kwargs, log=lambda s: None)


def _run(ctx, *, match_recs, align_recs, decision_recs=None):
    write_product(ctx, "glyph_match", PAGE,
                  glyph_match=page_match(PAGE, BOOK, recs=match_recs, col=COL))
    write_product(ctx, "align_ref", PAGE,
                  align_ref=page_align_ref(PAGE, BOOK, recs=align_recs, col=COL))
    if decision_recs is not None:
        write_product(ctx, "context_decide", PAGE,
                      context_decision=page_decision(PAGE, BOOK, recs=decision_recs, col=COL))
    return STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]


def _by_slot(sa):
    return {r.slot: r for cc in sa.columns for r in cc.chars}


# 三格：prev=山（slot1）、己已巳一族的格（slot2）、next=水（slot3）——
# 都不落在干支/时辰/「己」搭配任何一条规则里，纯靠「默认→已」vs 整理本区分。
_NEUTRAL_TRIO = [
    dict(slot=1, verdict="same", cov=1.0, wmax=0.0, char="山", candidates=[("山", 1.0)]),
    dict(slot=2, verdict="unsure", cov=0.5, wmax=0.0, candidates=[("巳", 0.5), ("已", 0.4)]),
    dict(slot=3, verdict="same", cov=1.0, wmax=0.0, char="水", candidates=[("水", 1.0)]),
]


def test_default_bucket_now_trusts_align_ref_over_hardcoded_yi(tmp_path, monkeypatch):
    """回归锁定这次的核心修复：非干支/时辰/搭配的格，`resolve()` 现在参考整理本
    （`use_ref="all"`），不再无条件默认成「已」。"""
    sa = _run(_ctx(tmp_path, monkeypatch), match_recs=_NEUTRAL_TRIO, align_recs=[
        dict(slot=1, align_char="山"), dict(slot=2, align_char="巳"),
        dict(slot=3, align_char="水")])
    r = _by_slot(sa)[2]
    assert r.char == "巳", f"整理本给了「巳」却仍判成别的字：{r.char}（旧默认会错判成「已」）"
    assert r.admit and r.channel == "split_ref"   # 非「干支/时辰」不改通道名，只改字


def test_ganzhi_still_wins_over_ref_and_default():
    """两侧都验：干支证据摆在那儿时，哪怕整理本给的是别的族内字，干支照旧压过去
    ——这条没被这次改动动过，用 `resolve()` 直接验（同 `test_ji_yi_si.py` 口径）。"""
    from open_guji_cv.utils.ji_yi_si import resolve
    assert resolve("日", "丑", "已", use_ref="all")[0] == "己"


def test_review_gate_off_by_default_keeps_old_admit_behavior(tmp_path, monkeypatch):
    """`ji_yi_si_review` 缺省关：三方（上下文/整理本/库top1）不一致也照旧放行
    ——用户 09-06/09-11「整理本给了就放行」的规矩，缺省不变。"""
    sa = _run(_ctx(tmp_path, monkeypatch), match_recs=_NEUTRAL_TRIO, align_recs=[
        dict(slot=1, align_char="山"), dict(slot=2, align_char="巳"),
        dict(slot=3, align_char="水")],
        decision_recs=[dict(slot=2, char="已", margin=0.9, source="context")])
    r = _by_slot(sa)[2]
    assert r.admit, "缺省关时不该被新闸拦——上下文/整理本不一致也该照旧放行"


def test_review_gate_on_blocks_disagreement(tmp_path, monkeypatch):
    """`ji_yi_si_review=True`：上下文定的字（已）与整理本（巳）不一致——三方不
    一致，送人审，不许自动放行。"""
    ctx = _ctx(tmp_path, monkeypatch, params=SeedAdmitParams(ji_yi_si_review=True))
    sa = _run(ctx, match_recs=_NEUTRAL_TRIO, align_recs=[
        dict(slot=1, align_char="山"), dict(slot=2, align_char="巳"),
        dict(slot=3, align_char="水")],
        decision_recs=[dict(slot=2, char="已", margin=0.9, source="context")])
    r = _by_slot(sa)[2]
    assert not r.admit, f"三方不一致却被放行：{r.channel}/{r.char}"
    assert "ji_yi_si_review" in r.doubts


def test_review_gate_on_admits_when_all_three_agree(tmp_path, monkeypatch):
    """三方（上下文=整理本=库 top1=巳）一致时，闸开着也照样放行。"""
    ctx = _ctx(tmp_path, monkeypatch, params=SeedAdmitParams(ji_yi_si_review=True))
    sa = _run(ctx, match_recs=_NEUTRAL_TRIO, align_recs=[
        dict(slot=1, align_char="山"), dict(slot=2, align_char="巳"),
        dict(slot=3, align_char="水")],
        decision_recs=[dict(slot=2, char="巳", margin=0.9, source="context")])
    r = _by_slot(sa)[2]
    assert r.admit and r.char == "巳", f"三方一致却没放行：{r.admit}/{r.char}/{r.doubts}"


def test_review_gate_does_not_touch_ganzhi_sure_cases(tmp_path, monkeypatch):
    """干支/时辰「几乎不会错」的格不受这条新闸影响——哪怕开着 `ji_yi_si_review`
    且上下文/库都没有独立证据，干支证据本身就该直接放行。"""
    ctx = _ctx(tmp_path, monkeypatch, params=SeedAdmitParams(ji_yi_si_review=True))
    match_recs = [
        dict(slot=1, verdict="same", cov=1.0, wmax=0.0, char="癸", candidates=[("癸", 1.0)]),
        dict(slot=2, verdict="unsure", cov=0.5, wmax=0.0, candidates=[("巳", 0.5), ("已", 0.4)]),
        dict(slot=3, verdict="same", cov=1.0, wmax=0.0, char="雨", candidates=[("雨", 1.0)]),
    ]
    sa = _run(ctx, match_recs=match_recs, align_recs=[
        dict(slot=1, align_char="癸"), dict(slot=2, align_char="已"),   # 整理本给错也不该拦干支
        dict(slot=3, align_char="雨")])
    r = _by_slot(sa)[2]
    assert r.admit and r.char == "巳" and r.channel == "ji_yi_si"
