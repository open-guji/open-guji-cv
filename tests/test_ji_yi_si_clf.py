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
    assert clf.classify("某", "見於")[0] is None            # 「已見」不是「己見」：前字不在 gate 里，不判


def test_yi_function_words():
    assert clf.classify("不過如此而", "矣")[0] == "已"
    assert clf.classify("業", "")[0] == "已"
    assert clf.classify("不", "")[0] is None
    assert clf.classify("不得", "")[0] == "已"
    assert clf.classify("某書", "經")[0] == "已"
    assert clf.classify("自", "經")[0] == "己"              # 自己 压过 已經


def test_yi_verb_time_next():
    # 已＋動詞/時間词（语料筛出，见 mine_yi_rules.py）
    assert clf.classify("某書", "久")[0] == "已"
    assert clf.classify("某書", "定")[0] == "已"
    assert clf.classify("田", "墾")[0] == "已"
    assert clf.classify("某", "畢")[0] == "已"
    assert clf.classify("某", "譏")[0] is None            # 语料里「譏」样本不足，不判
    assert clf.classify("自", "久")[0] == "己"            # 自己 压过 已久


def test_yi_ran():
    assert clf.classify("某", "然")[0] == "已"
    assert clf.classify("某", "然其")[0] == "已"
    assert clf.classify("無諸", "然後非諸人")[0] is None   # 「己|然後」：句读被吞，不判
    assert clf.classify("克", "然後")[0] == "己"           # 克己 + 然後


def test_yi_prev_time_words():
    assert clf.classify("既", "")[0] == "已"
    assert clf.classify("前", "有")[0] == "已"
    assert clf.classify("勝凡他人所", "言者")[0] == "已"   # 所已言
    assert clf.classify("五品", "上")[0] == "已"
    assert clf.classify("中書", "未召試")[0] is None       # 「書＋已」已剔除：中書己未
    assert clf.classify("前", "未")[0] is None             # 后字是地支留给干支规则
    assert clf.classify("既", "意")[0] == "己"             # 己意 优先


def test_ji_prev_narrowed():
    # 人名／书名／固定词尾后的「已」不能因前字在旧表里就判成己
    assert clf.classify("然歐陽修", "稱今但存")[0] is None       # 歐陽修已稱
    assert clf.classify("有周易說異", "著錄是編")[0] == "已"      # 說異已著錄（后字「著」→ 已＋動詞）
    assert clf.classify("現在", "有")[0] is None                   # 現在已有
    assert clf.classify("自", "性徹入")[0] == "己"                 # 自己：保留
    assert clf.classify("捨", "從人")[0] == "己"


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
    chars = "癸子丑未自克以而業得不意見說經矣有爲間月康熙某久然既前所品書後定畢"
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


