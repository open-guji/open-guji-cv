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


def test_v_pair_keeps_original_sources():
    """V 对补 local:pairkind 边时不能盖掉原来源（原文件常只存一个方向；QTW 11-22 #1781 对比后查出 74 对 n_bridge 掉到 1）。"""
    from open_guji_cv.pair_kind import TAG
    g = VariantGraph.load()
    src = g.sources_of("㑹", "會")
    assert TAG in src and "twedu" in src and "hydzd" in src, src
    assert g.sources_of("會", "㑹") == src


def test_look_alike_covers_c_pairs():
    """C 对删了关系图的边，但「形取谁说不准」的护栏照样拦（QTW 11-22 052:11:8:11 冲→沖）。"""
    from open_guji_cv.variants import are_variants, look_alike
    from open_guji_cv.steps.seed_admit import rare_ref_decide
    assert not are_variants("冲", "沖") and look_alike("冲", "沖")
    assert look_alike("會", "㑹") and not look_alike("甲", "乙") and not look_alike("沖", "沖")
    kw = dict(doubts=[], guard=None, verdict="unsure", lib_char=None, lib_top="冲", ref="沖", op="replace", rare_top="沖")
    assert rare_ref_decide(**kw, are_variants=look_alike) is None
