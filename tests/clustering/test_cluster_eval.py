"""cluster_eval.py 单测：分子分母、分层、难例对方向。"""

from open_guji_cv.clustering.cluster_eval import (compute_purity, evaluate,
                                                  hard_pair_report)

GOLD = {"a": "甲", "b": "甲", "c": "乙", "d": "乙", "e": "丙"}


def test_perfect_clustering():
    asg = {"a": "c1", "b": "c1", "c": "c2", "d": "c2", "e": "c3"}
    r = compute_purity(asg, GOLD)
    assert r.purity == 1.0
    assert r.n_clusters == 3 and r.n_gold_chars == 3
    assert r.fragmentation == 1.0
    assert r.impure_clusters == []


def test_dirty_cluster_counts_only_the_minority_as_wrong():
    asg = {"a": "c1", "b": "c1", "c": "c1", "d": "c2", "e": "c3"}
    r = compute_purity(asg, GOLD)
    assert (r.n_majority, r.n_instances) == (4, 5)     # c1 里多数是甲(2)，乙(1) 算错
    assert r.impure_clusters[0]["cluster_id"] == "c1"
    assert r.impure_clusters[0]["n_wrong"] == 1


def test_singletons_inflate_purity_but_not_multi_instance_purity():
    """全单例 purity=1.0，毫无用处——多实例簇 purity 必须把这份白送的摘掉。"""
    asg = {k: f"c{i}" for i, k in enumerate(GOLD)}
    r = compute_purity(asg, GOLD)
    assert r.purity == 1.0
    assert r.n_multi_instances == 0 and r.multi_instance_purity == 0.0
    assert r.singleton_ratio == 1.0
    assert r.fragmentation == 5 / 3


def test_instances_without_gold_are_out_of_the_denominator():
    asg = {"a": "c1", "b": "c1", "z": "c1"}
    r = compute_purity(asg, GOLD)
    assert r.n_instances == 2 and r.purity == 1.0


def test_subset_reuses_the_same_clustering():
    """分层不是重新聚类：簇结构不动，只按子集重数多数字。"""
    asg = {"a": "c1", "b": "c1", "c": "c1", "d": "c2", "e": "c2"}
    r = compute_purity(asg, GOLD, subset={"a", "b", "d"})
    assert r.n_instances == 3 and r.purity == 1.0      # 子集里 c1 只剩两个甲
    assert compute_purity(asg, GOLD).purity == 3 / 5   # 全量：c1 多数 2，c2 多数 1


def test_hard_pairs_directions_are_opposite():
    asg = {"a": "c1", "b": "c1", "c": "c1", "d": "c2"}
    pairs = [{"a": "a", "b": "b", "relation": "same", "origin": "t"},
             {"a": "a", "b": "d", "relation": "same", "origin": "t"},
             {"a": "a", "b": "c", "relation": "diff", "origin": "t"},
             {"a": "a", "b": "d", "relation": "diff", "origin": "t"}]
    r = hard_pair_report(asg, pairs)
    assert r["by_group"]["same/t"]["correct"] == 1
    assert r["by_group"]["diff/t"]["correct"] == 1
    assert r["overall"]["accuracy"] == 0.5
    assert {f["relation"] for f in r["failures"]} == {"same", "diff"}


def test_hard_pairs_missing_instances_are_counted_not_scored():
    r = hard_pair_report({"a": "c1"}, [{"a": "a", "b": "zzz",
                                        "relation": "same", "origin": "t"}])
    assert r["n_missing_instances"] == 1 and r["overall"]["n"] == 0


def test_evaluate_splits_strata_by_origin_and_align_op():
    instances = [{"instance_id": "a", "char": "甲", "label_origin": "align",
                  "align_op": "equal"},
                 {"instance_id": "b", "char": "甲", "label_origin": "align",
                  "align_op": "replace"},
                 {"instance_id": "c", "char": "乙", "label_origin": "human"}]
    asg = {"a": "c1", "b": "c1", "c": "c1"}
    r = evaluate(asg, instances, [])
    assert set(r["strata"]) == {"label_origin=align", "label_origin=human",
                                "align_op=equal", "align_op=replace"}
    assert r["strata"]["align_op=equal"]["purity_den"] == 1
    assert r["overall"]["purity_num"] == 2        # 簇里 甲×2 乙×1
