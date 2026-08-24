"""context_step 单测：策略注册表 + 与生产核心（seed context 通道）同源。"""

import pytest

from open_guji_cv.clustering.context_step import (GatedNgram, PriorTop1,
                                                  build_strategy)
from open_guji_cv.clustering.lm import CharNgramLM
from open_guji_cv.clustering.recognize_flow import (decide_unsure,
                                                    semantic_margin)
from open_guji_cv.clustering.match import MatchResult


def _lm(text: str) -> CharNgramLM:
    lm = CharNgramLM(order=3)
    lm.train([text])
    return lm


def test_prior_top1_ignores_context():
    d = build_strategy("prior")
    r = d.decide({"甲": 0.7, "乙": 0.3}, context=("随", "便"))
    assert r.surface == "甲" and r.margin > 0
    assert r.decision.ranked[0][0] == "甲"


def test_gated_ngram_matches_seed_channel():
    """铁律：策略核心与 seed 通道逐字节同源——同输入必同输出。"""
    lm = _lm("欽定四庫全書總目")
    sem = lambda c: {"珎": "珍"}.get(c, c)
    mr = MatchResult("unsure", None, None, 0.9, 5.0,
                     candidates=[("珎", 0.9)])
    topk = [("珍", 0.85)]
    ctx = ("四", "庫")
    dec = decide_unsure(mr, topk, context=ctx, lm=lm, semantic_fn=sem)
    surface, margin = semantic_margin(dec, sem, surface_prefs={"珎"})

    from open_guji_cv.clustering.recognize_flow import fuse_priors
    d = build_strategy("gated_ngram", lm=lm, semantic_fn=sem)
    r = d.decide(fuse_priors([("珎", 0.9)], topk), context=ctx,
                 surface_prefs={"珎"})
    assert r.surface == surface
    assert r.margin == pytest.approx(margin)
    assert [c for c, _ in r.decision.ranked] == [c for c, _ in dec.ranked]


def test_gated_ngram_lm_flips_within_candidates():
    """LM 能翻案，但只在候选集合内（字形层不可改写）。"""
    lm = _lm("大典大典大典")
    d = build_strategy("gated_ngram", lm=lm, semantic_fn=lambda c: c)
    r = d.decide({"曲": 0.52, "典": 0.48}, context=("大",))
    assert r.surface == "典"                    # 上下文救回
    r2 = d.decide({"曲": 0.52, "典": 0.48}, context=())
    assert r2.surface == "曲"                   # 无前文退化为先验


def test_build_strategy_errors():
    with pytest.raises(KeyError):
        build_strategy("no_such")
    with pytest.raises(ValueError):
        build_strategy("gated_ngram")
