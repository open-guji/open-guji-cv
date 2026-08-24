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
