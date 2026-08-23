"""recognize_flow 合成单测：候选融合 / margin / 退化路径 / diff 无库候选。"""

import math

import pytest

from open_guji_cv.clustering.lm import CharNgramLM, UniformLM
from open_guji_cv.clustering.match import MatchResult
from open_guji_cv.clustering.recognize_flow import (ColumnContext,
                                                    decide_diff,
                                                    decide_unsure,
                                                    fuse_priors)


def _unsure(cands):
    return MatchResult("unsure", None, None, 0.9, 5.0, candidates=cands)


# ── 候选融合 ────────────────────────────────────────────────


def test_fusion_union_and_db_weight_dominates():
    """候选集 = 库 ∪ OCR；权重同级时库候选（cov 高 + 权重高）应排前。"""
    d = decide_unsure(_unsure([("甲", 0.95)]), [("乙", 0.9)], s2t=False)
    chars = [c for c, _ in d.ranked]
    assert set(chars) == {"甲", "乙"}          # 两个来源都进候选集
    assert d.char == "甲"                      # w_db(3.0)·0.95 > w_ocr(1.5)·0.9
    assert d.branch == "unsure"


def test_fusion_same_char_from_both_sources_adds_up():
    """库与 OCR 指向同一个字 → 先验相加，压过单来源的更高分。"""
    priors = fuse_priors([("甲", 0.5), ("乙", 0.9)], [("甲", 0.9)], s2t=False)
    assert priors["甲"] > priors["乙"]         # 3·0.5+1.5·0.9=2.85 > 3·0.9=2.7
    assert abs(sum(priors.values()) - 1.0) < 1e-9


def test_fusion_ranked_descending_and_normalized():
    d = decide_unsure(_unsure([("甲", 0.9), ("乙", 0.88)]),
                      [("丙", 0.5)], s2t=False)
    ps = [p for _, p in d.ranked]
    assert ps == sorted(ps, reverse=True)
    assert abs(sum(ps) - 1.0) < 1e-9


def test_s2t_expansion_promotes_traditional_form():
    """OCR 输出简体（PP-OCR 字表偏差）→ s2t 扩展后繁体为主候选。"""
    d = decide_diff([("会", 0.9)])             # 刻本不可能有简体「会」
    chars = [c for c, _ in d.ranked]
    assert d.char == "會"
    assert "会" in chars                       # 原输出降权保留，不武断排除


# ── margin 计算 ─────────────────────────────────────────────


def test_margin_is_top1_minus_top2_after_softmax():
    """纯先验路径 softmax(log p) == p → margin 可手算验证。"""
    d = decide_unsure(_unsure([("甲", 0.9), ("乙", 0.3)]), [], s2t=False)
    # 先验归一：甲 0.75, 乙 0.25 → margin = 0.5
    assert d.margin == pytest.approx(0.5)
    assert d.ranked[0] == ("甲", pytest.approx(0.75))


def test_margin_single_candidate_is_one():
    d = decide_diff([("甲", 0.7)], s2t=False)
    assert d.char == "甲"
    assert d.margin == pytest.approx(1.0)


def test_margin_close_candidates_near_zero():
    d = decide_unsure(_unsure([("甲", 0.9), ("乙", 0.9)]), [], s2t=False)
    assert d.margin == pytest.approx(0.0, abs=1e-9)


# ── 上下文/LM 融合与退化路径 ───────────────────────────────


def _lm_favoring_bing():
    """在「甲乙」上下文里强烈偏好「丙」的 3-gram。"""
    lm = CharNgramLM(order=3)
    lm.train(["甲乙丙" * 50 + "丁"])
    return lm


def test_context_lm_flips_ranking():
    """先验偏「丁」，但上下文「甲乙」让 LM 把「丙」抬上 top1。"""
    mr = _unsure([("丁", 0.95), ("丙", 0.5)])
    lm = _lm_favoring_bing()
    with_ctx = decide_unsure(mr, [], context=("甲", "乙"), lm=lm, s2t=False)
    assert with_ctx.char == "丙"
    assert with_ctx.used_context and with_ctx.fallback is None


def test_no_context_degrades_to_prior_fusion():
    """拿不到上下文 → 纯先验融合：同一个 LM 不再影响排序，且有注明。"""
    mr = _unsure([("丁", 0.95), ("丙", 0.5)])
    lm = _lm_favoring_bing()
    for ctx in (None, ()):
        d = decide_unsure(mr, [], context=ctx, lm=lm, s2t=False)
        assert d.char == "丁"                  # 先验说了算
        assert not d.used_context
        assert d.fallback == "no_context"


def test_no_lm_degrades_even_with_context():
    d = decide_unsure(_unsure([("丁", 0.9), ("丙", 0.5)]), [],
                      context=("甲", "乙"), lm=None, s2t=False)
    assert d.char == "丁" and not d.used_context


def test_uniform_lm_keeps_prior_order():
    """UniformLM（logp 恒 0）下上下文路径与纯先验同序——回归融合公式。"""
    mr = _unsure([("甲", 0.9), ("乙", 0.4)])
    a = decide_unsure(mr, [], context=("丙",), lm=UniformLM(), s2t=False)
    b = decide_unsure(mr, [], s2t=False)
    assert [c for c, _ in a.ranked] == [c for c, _ in b.ranked]
    assert a.used_context


def test_semantic_fn_maps_before_lm():
    """LM 只见语义层：字形层候选经 semantic_fn 正字化后打分。"""
    sem = {"竝": "並"}.get
    lm = CharNgramLM(order=3)
    lm.train(["甲乙並" * 50])                  # 语料只有正字「並」
    mr = _unsure([("竝", 0.5), ("丁", 0.6)])
    d = decide_unsure(mr, [], context=("甲", "乙"), lm=lm,
                      semantic_fn=lambda c: sem(c, c), s2t=False)
    assert d.char == "竝"                      # 语义层得分抬字形层的「竝」


# ── diff 档 ────────────────────────────────────────────────


def test_diff_no_candidates_at_all():
    """OCR 一个字都没给（库候选本来就没有）→ char=None 进审查队列。"""
    d = decide_diff([])
    assert d.char is None
    assert d.margin == 0.0
    assert d.ranked == []
    assert d.fallback == "no_candidates"
    assert d.branch == "diff"


def test_diff_uses_only_ocr():
    d = decide_diff([("甲", 0.8), ("乙", 0.2)], s2t=False)
    assert d.char == "甲" and d.branch == "diff"
    assert d.margin == pytest.approx(0.6)      # 0.8 vs 0.2 归一后


# ── ColumnContext ──────────────────────────────────────────


def test_column_context_window_order_and_isolation():
    cc = ColumnContext(size=2)
    for i, ch in enumerate("甲乙丙"):
        cc.record("5", 1, i, ch)
    cc.record("5", 2, 0, "丁")                 # 别列
    assert cc.window("5", 1, 3) == ("乙", "丙")  # 最近 2 个，idx 升序
    assert cc.window("5", 1, 1) == ("甲",)     # 只取前文
    assert cc.window("5", 1, 0) == ()          # 列首无上下文
    assert cc.window("6", 1, 3) == ()          # 别页拿不到


def test_column_context_out_of_order_safe():
    """乱序登记：窗口只含 idx 更小的已定字，后文不会混进来。"""
    cc = ColumnContext(size=4)
    cc.record("5", 1, 10, "丙")
    cc.record("5", 1, 2, "甲")
    assert cc.window("5", 1, 5) == ("甲",)


def test_decision_to_dict_roundtrip_fields():
    d = decide_diff([("甲", 0.8)], s2t=False)
    payload = d.to_dict()
    assert payload["char"] == "甲"
    assert payload["branch"] == "diff"
    assert isinstance(payload["margin"], float)
    assert payload["ranked"][0][0] == "甲"
