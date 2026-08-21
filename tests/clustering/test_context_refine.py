"""context_refine 单测：簇级边缘化、自举语料、先验回灌。"""

import pytest

from open_guji_cv.clustering.context_rank import SlotResult
from open_guji_cv.clustering.context_refine import (apply_cluster_prior,
                                                    bootstrap_corpus,
                                                    cluster_marginalize)
from open_guji_cv.clustering.variants import VariantMap


def _res(iid, cid, posterior, best=None):
    best = best or posterior[0][0]
    return SlotResult(instance_id=iid, cluster_id=cid, posterior=posterior,
                      margin=posterior[0][1] - (posterior[1][1]
                                                if len(posterior) > 1 else 0),
                      best=best, best_semantic=best, suspect_reasons=[])


def test_cluster_marginalize_resolves_single_point_ambiguity():
    """聚类核心红利：单点模糊，但多处上下文联合证据指向同一字。

    三个实例各自都在 甲/乙 间摇摆（0.5/0.5 附近），但都略偏"甲"，
    联合后"甲"应显著胜出。
    """
    results = [
        _res("b:1:1:0", "c1", [("甲", 0.55), ("乙", 0.45)]),
        _res("b:1:1:5", "c1", [("甲", 0.60), ("乙", 0.40)]),
        _res("b:2:1:3", "c1", [("甲", 0.52), ("乙", 0.48)]),
    ]
    post = dict(cluster_marginalize(results, {r.instance_id: "c1"
                                              for r in results})["c1"])
    assert post["甲"] > post["乙"]
    assert post["甲"] > 0.55        # 联合后比任一单点更确定


def test_cluster_marginalize_geometric_mean_scale():
    """大小簇的分布尺度可比（按实例数几何平均，不因簇大而失控）。"""
    small = [_res("b:1:1:0", "c1", [("甲", 0.9), ("乙", 0.1)])]
    big = [_res(f"b:1:1:{i}", "c2", [("甲", 0.9), ("乙", 0.1)])
           for i in range(50)]
    p_small = dict(cluster_marginalize(small, {"b:1:1:0": "c1"})["c1"])
    ids = {r.instance_id: "c2" for r in big}
    p_big = dict(cluster_marginalize(big, ids)["c2"])
    assert abs(p_small["甲"] - p_big["甲"]) < 0.05


def test_bootstrap_corpus_takes_confident_runs_only():
    """只有连续 ≥3 个高置信字才入语料；低置信打断段落。"""
    vm = VariantMap({})
    results = [
        _res("b:1:1:0", "c", [("天", 0.95)]),
        _res("b:1:1:1", "c", [("下", 0.92)]),
        _res("b:1:1:2", "c", [("太", 0.91)]),
        _res("b:1:1:3", "c", [("平", 0.30), ("凡", 0.28)]),   # 低置信，断
        _res("b:1:1:4", "c", [("甲", 0.99)]),
        _res("b:1:1:5", "c", [("乙", 0.99)]),                  # 只有 2 个，弃
    ]
    assert bootstrap_corpus(results, vm) == ["天下太"]


def test_bootstrap_corpus_normalizes_to_semantic_layer():
    """语料是语义层（异体字正字化），与 LM 打分空间一致。"""
    vm = VariantMap({"逰": "遊"})
    results = [_res(f"b:1:1:{i}", "c", [(ch, 0.95)])
               for i, ch in enumerate("逰山玩水")]
    for r, ch in zip(results, "逰山玩水"):
        r.best_semantic = vm.semantic(ch)
    assert bootstrap_corpus(results, vm) == ["遊山玩水"]


def test_apply_cluster_prior_shifts_but_keeps_glyph_layer():
    """回灌先验改变概率，但不合并任何字形、不引入语义层替换。"""
    cands = {"c1": [{"char": "日", "semantic": "日", "p": 0.55,
                     "sources": ["ocr"], "surface_uncertain": True},
                    {"char": "曰", "semantic": "曰", "p": 0.45,
                     "sources": ["ocr"], "surface_uncertain": True}]}
    post = {"c1": [("曰", 0.9), ("日", 0.1)]}
    out = apply_cluster_prior(cands, post, weight=0.6)["c1"]
    assert out[0]["char"] == "曰"          # 簇级证据翻转了首选
    assert {c["char"] for c in out} == {"日", "曰"}   # 两个字形都还在
    assert abs(sum(c["p"] for c in out) - 1.0) < 0.01


def test_apply_cluster_prior_noop_without_posterior():
    cands = {"c1": [{"char": "甲", "semantic": "甲", "p": 1.0,
                     "sources": ["vlm"], "surface_uncertain": False}]}
    assert apply_cluster_prior(cands, {}) == cands


def test_cluster_prior_never_degrades_confident_candidates():
    """回归：簇级边缘化不得把"全簇一致的高置信候选"改坏。

    book9 全书消融验证的性质（黄金集 5013 实例零劣化）——
    这是它可以默认开启、而自举 LM 不能的原因。
    """
    from open_guji_cv.clustering.context_refine import (apply_cluster_prior,
                                                        cluster_marginalize)
    # 全簇 20 个实例都高置信认定"甲"
    results = [_res(f"b:1:1:{i}", "c1", [("甲", 0.95), ("乙", 0.05)])
               for i in range(20)]
    post = cluster_marginalize(results, {r.instance_id: "c1" for r in results})
    cands = {"c1": [{"char": "甲", "semantic": "甲", "p": 0.95,
                     "sources": ["vlm"], "surface_uncertain": False},
                    {"char": "乙", "semantic": "乙", "p": 0.05,
                     "sources": ["ocr"], "surface_uncertain": True}]}
    out = apply_cluster_prior(cands, post)["c1"]
    assert out[0]["char"] == "甲"
    assert out[0]["p"] > 0.9


def test_refine_defaults_to_cluster_prior_only():
    """默认配置不启用自举 LM（实测净有害）。"""
    import inspect
    from open_guji_cv.clustering.context_refine import refine_book
    sig = inspect.signature(refine_book)
    assert sig.parameters["use_lm"].default is False
    assert sig.parameters["use_cluster_prior"].default is True
