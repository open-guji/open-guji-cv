# -*- coding: utf-8 -*-
"""己/已/巳 词组分类器（overview#443，Z-jys）：`utils/ji_yi_si_clf` + `seed_admit.ji_yi_si_clf`。自造数据。"""
from __future__ import annotations

import importlib.util
import itertools
import json
from pathlib import Path

import open_guji_cv.steps  # noqa: F401
import open_guji_cv.utils.ji_yi_si_clf as clf
from helpers import make_book, page_align_ref, page_match, write_product
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1


# ---- 规则路（纯函数）：每条规则 ≥2 正例 ≥1 反例 ----
def test_ganzhi_prev_gan():
    assert clf.classify("康熙癸", "年")[0] == "巳"
    assert clf.classify("乙", "")[0] == "巳"


def test_ganzhi_prev_ji_is_not_gan():
    # 前字是「己」（可能刚被放行成「自己」的己）：不当天干判巳
    assert clf.classify("自己", "經")[0] == "已"          # 自己＋已經
    assert clf.classify("克己", "矣")[0] == "已"
    assert clf.classify("克己", "")[0] is None            # 不得是「巳」
    assert clf.classify("康熙己", "年")[0] is None


def test_ganzhi_chen_si_jian():
    assert clf.classify("辰", "間")[0] == "巳"
    assert clf.classify("寅", "間")[0] is None            # 只认辰巳間，其他地支＋間不判
    assert clf.classify("午", "間")[0] is None
    assert clf.classify("某", "間")[0] is None


def test_ganzhi_next_zhi():
    assert clf.classify("順治", "丑")[0] == "己"
    assert clf.classify("某", "酉")[0] == "己"
    assert clf.classify("而", "未嘗")[0] == "已"           # 「而已未嘗」：未 需日期语境，不当干支
    assert clf.classify("康熙", "未")[0] == "己"           # 年号末字 → 日期语境


def test_ji_self():
    assert clf.classify("斷以", "意")[0] == "己"
    assert clf.classify("參以", "見")[0] == "己"
    assert clf.classify("克", "復禮")[0] == "己"
    assert clf.classify("據爲", "有")[0] == "己"
    assert clf.classify("前", "見於")[0] is None            # 「已見」不是「己見」：前字不在 gate 里，不判


def test_yi_function_words():
    assert clf.classify("不過如此而", "矣")[0] == "已"
    assert clf.classify("業", "")[0] == "已"
    assert clf.classify("不", "")[0] is None
    assert clf.classify("不得", "")[0] == "已"
    assert clf.classify("某書", "經")[0] == "已"
    assert clf.classify("自", "經")[0] == "己"              # 自己 压过 已經


def test_er_yi_exception_title():
    # 书名《己易》被「而已」规则误伤（vol05:36:6:15）→ 弃权
    assert clf.classify("名徒生轇轕而", "易芥八卷")[0] is None


def test_unknown_blocks():
    assert clf.classify("□", "□")[0] is None
    assert clf.classify("而□", "□")[0] is None             # 紧邻是未知字，不越过去


def test_research_rules_parity():
    """research 里的研究版规则与管线内定型版逐上下文一致（除 research 版没加的例外已同步）。"""
    p = Path(__file__).resolve().parents[1] / "research/char_groups/jys/rules.py"
    spec = importlib.util.spec_from_file_location("jys_rules_research", p)
    rs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs)
    chars = "癸子丑未自克以而業得不意見說經矣有爲間月康熙某"
    for l, r in itertools.product(chars, repeat=2):
        for pre in ("", "不"):
            assert clf.classify(pre + l, r)[0] == rs.classify(pre + l, r)[0], (pre + l, r)


# ---- 答案表 ----
def _table(tmp_path, cells):
    p = tmp_path / "clf_table.json"
    p.write_text(json.dumps({"cells": cells}), encoding="utf-8")
    clf._load.cache_clear()
    return str(p)


def test_suggest_needs_both_passes_and_lr(tmp_path):
    k = clf.ctx_key("山", "水")
    t = _table(tmp_path, {
        "a": {"ctx": k, "llm": ["己", "己"], "lr": "己", "lr_margin": 0.9},
        "b": {"ctx": k, "llm": ["己", "已"], "lr": "己", "lr_margin": 0.9},
        "c": {"ctx": k, "llm": ["己", "己"], "lr": "已", "lr_margin": 0.9},
        "d": {"ctx": "xxxx", "llm": ["己", "己"], "lr": "己", "lr_margin": 0.9}})
    assert clf.suggest(t, "a", "山", "水")["char"] == "己"
    assert clf.suggest(t, "b", "山", "水")["char"] is None
    assert clf.suggest(t, "c", "山", "水")["char"] is None
    assert clf.suggest(t, "d", "山", "水") == {"char": None, "why": "ctx_mismatch"}
    assert clf.suggest(t, "zz", "山", "水") is None
    assert clf.suggest("", "a", "山", "水") is None


def test_ctx_key_cuts_at_unknown():
    assert clf.ctx_key("甲□乙丙", "丁□戊") == clf.ctx_key("乙丙", "丁")


# ---- seed_admit 接线 ----
def test_param_default_off_and_hash_unchanged():
    d = SeedAdmitParams().model_dump()
    assert SeedAdmitParams().ji_yi_si_clf is False
    assert not any(k.startswith("ji_yi_si_clf") for k in d)         # 关时不进 dump，params_hash 不变
    on = SeedAdmitParams(ji_yi_si_clf=True).model_dump()
    assert on["ji_yi_si_clf"] is True and "ji_yi_si_clf_llm" not in on
    on2 = SeedAdmitParams(ji_yi_si_clf=True, ji_yi_si_clf_llm=True).model_dump()
    assert "ji_yi_si_clf_margin" in on2


def test_table_fingerprint_follows_content(tmp_path):
    t = _table(tmp_path, {"a": {"ctx": "k", "llm": ["己", "己"], "lr": "己"}})
    f1 = SeedAdmitParams(ji_yi_si_clf=True, ji_yi_si_clf_table=t).ji_yi_si_clf_fingerprint
    t = _table(tmp_path, {"a": {"ctx": "k", "llm": ["已", "已"], "lr": "已"}})
    f2 = SeedAdmitParams(ji_yi_si_clf=True, ji_yi_si_clf_table=t).ji_yi_si_clf_fingerprint
    assert f1 and f2 and f1 != f2


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


def test_rule_hit_admits_and_ignores_ref(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, SeedAdmitParams(ji_yi_si_clf=True))
    r = _run(ctx, "而", "矣", ref="巳")      # 整理本给「巳」，规则说「已」
    assert r.admit and r.char == "已" and r.channel == "ji_yi_si"
    assert r.evidence["ji_yi_si_clf"]["rule"] == "已" and r.evidence["ji_yi_si_clf"]["via"] == "rule"


def test_rule_abstain_retires_split_ref(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, SeedAdmitParams(ji_yi_si_clf=True))
    r = _run(ctx, "山", "水", ref="巳")      # 规则不命中：整理本路放行退役 → 送审
    assert not r.admit and r.char is None
    assert "ji_yi_si_clf_review" in r.doubts


def test_abstain_writes_suggestion_but_does_not_admit(tmp_path, monkeypatch):
    t = _table(tmp_path, {"tbook:1:1:2": {"ctx": clf.ctx_key("山", "水"), "llm": ["己", "己"], "lr": "己", "lr_margin": 0.9}})
    ctx = _ctx(tmp_path, monkeypatch, SeedAdmitParams(ji_yi_si_clf=True, ji_yi_si_clf_table=t))
    r = _run(ctx, "山", "水", ref="巳")
    assert not r.admit
    assert r.evidence["ji_yi_si_clf"]["suggest"]["char"] == "己"


def test_llm_switch_admits_with_margin(tmp_path, monkeypatch):
    cell = {"ctx": clf.ctx_key("山", "水"), "llm": ["己", "己"], "lr": "己", "lr_margin": 0.9}
    t = _table(tmp_path, {"tbook:1:1:2": cell})
    ctx = _ctx(tmp_path, monkeypatch, SeedAdmitParams(ji_yi_si_clf=True, ji_yi_si_clf_llm=True, ji_yi_si_clf_table=t))
    r = _run(ctx, "山", "水", ref="巳")
    assert r.admit and r.char == "己" and r.evidence["ji_yi_si_clf"]["via"] == "llm+lr"
    # 差值不够 → 不放行
    t2 = _table(tmp_path, {"tbook:1:1:2": {**cell, "lr_margin": 0.1}})
    ctx = _ctx(tmp_path, monkeypatch, SeedAdmitParams(ji_yi_si_clf=True, ji_yi_si_clf_llm=True, ji_yi_si_clf_table=t2))
    assert not _run(ctx, "山", "水", ref="巳").admit


def test_neighbor_pending_default_char_is_not_used(tmp_path, monkeypatch):
    """待审邻格的 `char` 是库 top1 默认字（可能乱码），规则只用已放行字，否则用整理本字。"""
    ctx = _ctx(tmp_path, monkeypatch, SeedAdmitParams(ji_yi_si_clf=True))
    recs = [
        # 左邻待审：默认字「而」（库 top1），整理本是「山」
        dict(slot=1, verdict="unsure", cov=0.3, wmax=0.0, candidates=[("而", 0.5), ("山", 0.4)]),
        dict(slot=2, verdict="unsure", cov=0.5, wmax=0.0, candidates=[("巳", 0.5), ("已", 0.4)]),
        dict(slot=3, verdict="same", cov=1.0, wmax=0.0, char="水", candidates=[("水", 1.0)]),
    ]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
        PAGE, BOOK, recs=[dict(slot=1, align_char="山"), dict(slot=2, align_char="巳"),
                          dict(slot=3, align_char="水")], col=COL))
    sa = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    r = {c.slot: c for cc in sa.columns for c in cc.chars}[2]
    assert not r.admit                                  # 若误用默认字「而」，会命中「而已」放行
    assert r.evidence["ji_yi_si_clf"]["rule"] is None
