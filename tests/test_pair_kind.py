"""字对关系表：语义表与关系图对同一对字答案一致（sheldon 2026-11-21）。"""
from open_guji_cv.clustering.variants import VariantMap
from open_guji_cv.pair_kind import C, V, load_pair_kinds, pair_kind
from open_guji_cv.variants import VariantGraph


def test_pair_kind_lookup_unordered():
    assert pair_kind("土", "士") == C and pair_kind("士", "土") == C
    assert pair_kind("會", "㑹") == V
    assert pair_kind("甲", "乙") is None


def test_semantic_and_graph_agree_with_table():
    vm, g = VariantMap.load(), VariantGraph.load()
    for key, kind in load_pair_kinds().items():
        a, b = sorted(key)
        assert (vm.semantic(a) == vm.semantic(b)) == (kind == V), (a, b, kind)
        assert g.are_variants(a, b) == (kind == V), (a, b, kind)


def test_explicit_path_ignores_table():
    assert VariantMap.load("/nonexistent.tsv").semantic("士") == "士"
