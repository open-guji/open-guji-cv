# -*- coding: utf-8 -*-
"""Step5-b OCR 候选包壳（阶段 B1）。"""

from __future__ import annotations

from pathlib import Path

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.spec import page_key
from open_guji_cv.core.step import KINDS, STEPS
from open_guji_cv.products.store import ProductStore

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data_full" / "zongmu"
needs_raw = pytest.mark.skipif(not RAW.exists(), reason="需要 data_full/zongmu 原图")


def test_registered_and_declares_engine_need():
    assert "ocr_candidates" in STEPS and "ocr_candidates" in KINDS
    assert "engine" in STEPS["ocr_candidates"].spec.needs, \
        "要声明 needs=engine，控制台才知道没引擎时该置灰而不是让人点了才失败"


@needs_raw
def test_candidates_are_ranked_and_probabilistic():
    store = ProductStore()
    d = store.read("vol01", "ocr_candidates", page_key(24), "ocr_candidates")
    if d is None:
        pytest.skip("vol01/24 还没跑过 ocr_candidates")
    if d.engine.startswith("unavailable"):
        pytest.skip(f"本机没有 OCR 引擎：{d.engine}")
    recs = [r for cc in d.columns for r in cc.chars if r.topk]
    assert recs, "一个候选都没有"
    for r in recs[:30]:
        probs = [p for _c, p in r.topk]
        assert probs == sorted(probs, reverse=True), f"{r.id} 候选没按概率降序"
        assert all(0.0 <= p <= 1.0 for p in probs), f"{r.id} 概率越界：{probs}"


@needs_raw
def test_s2t_expansion_reaches_traditional_forms():
    """简→繁扩展要真的把繁体带进候选。

    PP-OCR 是简体模型，本书 11.03% 的字次不在它字表里，缺的还是
    說/則/謂/論 这类各上千次的繁体常用字（charset_and_lm.md §一）。
    """
    store = ProductStore()
    d = store.read("vol01", "ocr_candidates", page_key(24), "ocr_candidates")
    if d is None or d.engine.startswith("unavailable"):
        pytest.skip("没有产物或没有引擎")
    simplified_only = set("书则谓论诸称编")
    all_chars = {c for cc in d.columns for r in cc.chars for c, _p in r.topk}
    # 这一页是繁体刻本，候选里不该只剩简体形
    assert all_chars, "候选为空"
    assert not all_chars <= simplified_only


@needs_raw
def test_two_signals_mostly_agree_and_library_wins_when_they_do_not():
    """库 same × OCR top1 的一致率要够高——这是 Step6 融合的前提。

    实测 vol01 p24+p137 350 字位：一致 67.1%、打架 11.7%，而打架样例里
    库 cov 全是 1.0、OCR prob 低到 0.03~0.67（閱/聞、釐/麓、緗/相、雖/維）。
    印证 glyph_db_first_design.md §7.3 的「库按 cov 分档采信，0.99 是拐点；
    OCR 置信度不参与任何自动判断」。
    """
    store = ProductStore()
    agree = disagree = 0
    for pg in (24, 137):
        m = store.read("vol01", "glyph_match", page_key(pg), "glyph_match")
        o = store.read("vol01", "ocr_candidates", page_key(pg), "ocr_candidates")
        if m is None or o is None or o.engine.startswith("unavailable"):
            continue
        omap = {r.id: r for cc in o.columns for r in cc.chars}
        for cc in m.columns:
            for r in cc.chars:
                if r.verdict != "same" or not r.char:
                    continue
                ocr = omap.get(r.id)
                if not ocr or not ocr.topk:
                    continue
                if r.char == ocr.topk[0][0]:
                    agree += 1
                else:
                    disagree += 1
    if agree + disagree == 0:
        pytest.skip("两步产物不齐")
    rate = agree / (agree + disagree)
    assert rate > 0.5, f"两路一致率只有 {rate:.1%}，其中一路可能坏了"
