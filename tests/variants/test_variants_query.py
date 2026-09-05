"""open_guji_cv/variants.py 查询模块单测：构造小表，不依赖构建产物与网络。"""

import json

import pytest

from open_guji_cv.variants import HIGH_CONFIDENCE_SOURCES, VariantGraph

# 小表：甲-乙 高置信（twedu），乙-丙 仅低置信（hydzd），
# 丁-戊 仅 spoofing（形近易混，非异体），己 是孤立字（不在表里）。
PAIRS = {
    "甲": {"乙": ["twedu", "unihan:kSemanticVariant"]},
    "乙": {"丙": ["hydzd"]},
    "丁": {"戊": ["unihan:kSpoofingVariant"]},
}


@pytest.fixture()
def graph():
    return VariantGraph(PAIRS)


def test_variants_of_bidirectional_with_tags(graph):
    assert graph.variants_of("甲") == [("乙", ("twedu", "unihan:kSemanticVariant"))]
    # 反方向也可查（表里只存了单侧）
    assert ("甲", ("twedu", "unihan:kSemanticVariant")) in graph.variants_of("乙")
    assert graph.variants_of("己") == []


def test_variants_of_sorted_by_codepoint():
    g = VariantGraph({"丙": {"甲": ["twedu"], "乙": ["twedu"]}})
    assert [c for c, _ in g.variants_of("丙")] == sorted("甲乙")


def test_are_variants_symmetric(graph):
    assert graph.are_variants("甲", "乙")
    assert graph.are_variants("乙", "甲")
    assert graph.are_variants("丁", "戊")      # spoofing 也算「有边」，靠标签区分
    assert not graph.are_variants("甲", "丙")  # 不传递
    assert not graph.are_variants("甲", "己")


def test_sources_of(graph):
    assert graph.sources_of("乙", "甲") == ("twedu", "unihan:kSemanticVariant")
    assert graph.sources_of("甲", "丙") == ()


def test_variant_group_default_walks_only_trusted(graph):
    # 乙-丙 只有 hydzd（不在默认高置信集），默认展开止步于乙
    assert graph.variant_group("甲") == {"甲", "乙"}
    assert "unihan:kSpoofingVariant" not in HIGH_CONFIDENCE_SOURCES
    assert graph.variant_group("丁") == {"丁"}   # spoofing 边默认不走


def test_variant_group_all_sources_bridges(graph):
    # sources=None 全来源都走——多义桥接风险由调用方自负
    assert graph.variant_group("甲", sources=None) == {"甲", "乙", "丙"}


def test_variant_group_custom_sources(graph):
    assert graph.variant_group("丙", sources={"hydzd"}) == {"乙", "丙"}
    assert graph.variant_group("丁", sources={"unihan:kSpoofingVariant"}) \
        == {"丁", "戊"}


def test_variant_group_isolated_char(graph):
    assert graph.variant_group("己") == {"己"}


def test_len_and_contains(graph):
    assert len(graph) == 5      # 甲乙丙丁戊
    assert "甲" in graph and "己" not in graph


def test_load_from_json(tmp_path):
    p = tmp_path / "variants.json"
    p.write_text(json.dumps({"meta": {}, "pairs": PAIRS}, ensure_ascii=False),
                 encoding="utf-8")
    g = VariantGraph.load(p)
    assert g.are_variants("乙", "甲")


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        VariantGraph.load(tmp_path / "nope.json")


# ── 有向部分（2026-09-05）────────────────────────────────
# 略/畧 纯异体；囘 一形多正（回/迴）；后/後 两头都是教育部正字（互通）；
# 子/只 只有 kSemanticVariant 却是不相干的字（关系层给不出，靠用字账）；
# 发/發/髮 只有简繁边；仍/乃 通假。

DPAIRS = {
    "略": {"畧": ["hydzd", "twedu"]},
    "回": {"囘": ["twedu"], "迴": ["hydzd"]},
    "囘": {"迴": ["twedu"]},
    "后": {"後": ["twedu", "yitizi", "unihan:kTraditionalVariant"]},
    "子": {"只": ["unihan:kSemanticVariant"]},
    "发": {"發": ["unihan:kTraditionalVariant"], "髮": ["unihan:kTraditionalVariant"]},
    "乃": {"仍": ["hydzd-borrowed"]},
    "將": {"疆": ["unihan:kSpecializedSemanticVariant"]},
}
DIRECTED = {
    "畧": {"略": ["hydzd", "twedu"]},
    "囘": {"回": ["twedu"], "迴": ["twedu"]},
    "后": {"後": ["twedu", "unihan:kTraditionalVariant"]},
    "妑": {"后": ["twedu"]},          # 让 后 自己也是教育部正字（名下有异体）
    "发": {"發": ["unihan:kTraditionalVariant"], "髮": ["unihan:kTraditionalVariant"]},
}


@pytest.fixture()
def dgraph():
    return VariantGraph(DPAIRS, DIRECTED)


def test_regulars_and_irregulars(dgraph):
    assert dgraph.regulars_of("畧") == [("略", ("hydzd", "twedu"))]
    assert dgraph.regulars_of("略") == []                       # 略 是正字
    assert [v for v, _ in dgraph.irregulars_of("回")] == ["囘"]
    assert dgraph.regulars_of("囘", sources={"hydzd"}) == []   # 来源过滤


def test_is_regular_by_twedu(dgraph):
    assert dgraph.is_regular("略") and dgraph.is_regular("後") and dgraph.is_regular("后")
    assert not dgraph.is_regular("畧")
    assert not dgraph.is_regular("發")                          # 只有 unihan 简繁指认


def test_one_to_many(dgraph):
    assert dgraph.is_one_to_many("囘")
    assert dgraph.is_one_to_many("发")
    assert not dgraph.is_one_to_many("畧")
    assert not dgraph.is_one_to_many("发", sources={"twedu"})  # 简繁来源不算时


def test_canonical_of(dgraph):
    assert dgraph.canonical_of("畧") == "略"
    assert dgraph.canonical_of("略") == "略"          # 正字归自己
    assert dgraph.canonical_of("甲") == "甲"          # 表里没有也归自己
    assert dgraph.canonical_of("囘") is None          # 一对多且 twedu 也给了两个
    assert dgraph.canonical_of("后") == "後"


def test_edge_tier_priors(dgraph):
    assert dgraph.edge_tier("略", "畧") == "T1"
    assert dgraph.edge_tier("畧", "略") == "T1"       # 方向无关
    assert dgraph.edge_tier("回", "囘") == "T2"       # 囘 一形多正
    assert dgraph.edge_tier("后", "後") == "T2"       # 兩正互通
    assert dgraph.edge_tier("將", "疆") == "T2"       # kSpecializedSemanticVariant
    assert dgraph.edge_tier("发", "發") == "T3"       # 只有简繁边
    assert dgraph.edge_tier("乃", "仍") == "T3"       # 通假
    assert dgraph.edge_tier("子", "只") == "T1"       # 关系层看不出它是 T3——用字账的活
    assert dgraph.edge_tier("略", "回") is None


def test_graph_without_directed_section_still_works():
    g = VariantGraph({"略": {"畧": ["twedu"]}})
    assert g.regulars_of("畧") == [] and g.canonical_of("畧") == "畧"
    assert g.edge_tier("略", "畧") == "T1"


def test_load_reads_directed(tmp_path):
    p = tmp_path / "variants.json"
    p.write_text(json.dumps({"meta": {}, "pairs": DPAIRS, "directed": DIRECTED},
                            ensure_ascii=False), encoding="utf-8")
    g = VariantGraph.load(p)
    assert g.canonical_of("畧") == "略"
