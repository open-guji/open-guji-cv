# -*- coding: utf-8 -*-
"""Step5-b OCR 候选包壳（阶段 B1）。

2026-09-20 重写：原先三条都读工作区里 vol01/24 的产物，且**还要本机装着
OCR 引擎**，两个条件缺一就 skip——云端两样都没有，三条一条没跑过。

现在分两半：
- 包壳自己的行为（候选降序、概率区间、简→繁扩展真的接上、没引擎时整页
  空候选而不是炸）用一个**桩引擎**测，不需要真装 rapidocr；
- 「库 same × OCR top1 的一致率」那条是**跨信号的质量测量**，不是代码行为，
  已迁出测试——它要真引擎 + 真书两页产物，且断言的是数据分布。同一个量
  由评测负责（`guji eval run`，口径见 doc/charset_and_lm.md §一）。
"""

from __future__ import annotations

import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, run_keben_from_raw
from open_guji_cv.core.step import KINDS, STEPS
from open_guji_cv.steps.ocr_candidates import OcrCandidatesParams

PAGE = 1


class _StubOcr:
    """固定返回一串简体候选的桩引擎——包壳要测的是它拿到 raw 之后做了什么。"""

    def __init__(self, raw: list[tuple[str, float]]):
        self.raw = raw

    def rec_topk(self, img):
        return list(self.raw)


def _run(tmp_path, monkeypatch, fixture_page, raw, **params):
    from open_guji_cv.core.book import load_book

    ctx, _ = run_keben_from_raw(tmp_path, monkeypatch, book=load_book("keben"),
                                gray=fixture_page, through="cell_shrink")
    step = STEPS["ocr_candidates"]
    monkeypatch.setattr(type(step), "_source", lambda self, p: _StubOcr(raw))
    ctx.params["ocr_candidates"] = OcrCandidatesParams(**params)
    return step.run_page(ctx, PAGE)["ocr_candidates"]


def test_registered_and_declares_engine_need():
    assert "ocr_candidates" in STEPS and "ocr_candidates" in KINDS
    assert "engine" in STEPS["ocr_candidates"].spec.needs, \
        "要声明 needs=engine，控制台才知道没引擎时该置灰而不是让人点了才失败"


def test_candidates_are_ranked_and_probabilistic(tmp_path, monkeypatch, ws,
                                                 fixture_page):
    """候选按概率降序、概率落在 [0,1]——下游按名次取用，乱序会静默取错字。"""
    d = _run(tmp_path, monkeypatch, fixture_page,
             [("书", 0.7), ("则", 0.2), ("谓", 0.05)])
    recs = [r for cc in d.columns for r in cc.chars if r.topk]
    assert recs, "一个候选都没有"
    for r in recs:
        probs = [p for _c, p in r.topk]
        assert probs == sorted(probs, reverse=True), f"{r.id} 候选没按概率降序"
        assert all(0.0 <= p <= 1.0 for p in probs), f"{r.id} 概率越界：{probs}"


def test_s2t_expansion_reaches_traditional_forms(tmp_path, monkeypatch, ws,
                                                 fixture_page):
    """简→繁扩展要真的把繁体带进候选。

    PP-OCR 是简体模型，本书 11.03% 的字次不在它字表里，缺的还是
    說/則/謂/論 这类各上千次的繁体常用字（charset_and_lm.md §一）。

    桩引擎只吐简体，所以**候选里出现繁体，只可能是扩展做出来的**——
    这比在真数据上看「候选不全是简体」严实得多。
    """
    simplified = [("书", 0.7), ("则", 0.2), ("谓", 0.05)]
    d = _run(tmp_path, monkeypatch, fixture_page, simplified, s2t=True)
    got = {c for cc in d.columns for r in cc.chars for c, _p in r.topk}
    assert got, "候选为空"
    assert got - {c for c, _ in simplified}, f"一个繁体都没扩出来：{sorted(got)}"
    assert {"書", "則", "謂"} & got, f"常用繁体没进候选：{sorted(got)}"


def test_s2t_off_keeps_the_engine_output_verbatim(tmp_path, monkeypatch, ws,
                                                  fixture_page):
    """关掉扩展就原样透传——两条路都要守，否则开关形同虚设。"""
    simplified = [("书", 0.7), ("则", 0.2)]
    d = _run(tmp_path, monkeypatch, fixture_page, simplified, s2t=False)
    got = {c for cc in d.columns for r in cc.chars for c, _p in r.topk}
    assert got == {"书", "则"}, got


def test_missing_engine_yields_empty_candidates_not_a_crash(tmp_path, monkeypatch,
                                                            ws, fixture_page):
    """引擎不在时整页空候选、engine 标 `unavailable:…`，不炸整条管线
    ——这是模块头写明的降级契约（没装引擎的机器照样要能跑完链路）。"""
    from open_guji_cv.core.book import load_book

    ctx, _ = run_keben_from_raw(tmp_path, monkeypatch, book=load_book("keben"),
                                gray=fixture_page)
    step = STEPS["ocr_candidates"]

    def _boom(self, p):
        raise RuntimeError("没有引擎")

    monkeypatch.setattr(type(step), "_source", _boom)
    d = step.run_page(ctx, PAGE)["ocr_candidates"]
    assert d.engine.startswith("unavailable:"), d.engine
    assert d.columns and all(not cc.ok for cc in d.columns)
    assert all(cc.error for cc in d.columns), "降级了却没说为什么"
