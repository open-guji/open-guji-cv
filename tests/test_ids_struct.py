# -*- coding: utf-8 -*-
"""IDS 结构层（`clustering/ids_struct.py`，M0 第一块）的回归。

钉住四件事：解析器对元数/无码部件的处理、主拆法的 T 优先、停集展开给出的
槽位部件、倒排索引的查询语义。**不测重排效果**——`component_consistency`
只是函数，接不接进 RRF 要等靶子量过（设计稿 §11 #3）。
"""

from __future__ import annotations

import pytest

from open_guji_cv.clustering.ids_struct import (IDC, SINGLE, IdsIndex, Node,
                                                component_consistency, struct_rerank,
                                                load_table, parse_ids,
                                                pick_primary, shared_index,
                                                structure_of, tokenize)


def test_tokenize_keeps_unencoded_component_as_one_token():
    assert tokenize("⿰{CDP-8BC5}攵") == ["⿰", "{CDP-8BC5}", "攵"]


@pytest.mark.parametrize("seq,leaves", [
    ("⿰言俞", ["言", "俞"]),
    ("⿳十罒心", ["十", "罒", "心"]),          # 三目
    ("⿰氵⿱艹⿰木木", ["氵", "艹", "木", "木"]),  # 嵌套
    ("⿾卩", ["卩"]),                          # 单目镜像
])
def test_parse_arity(seq, leaves):
    t = parse_ids(seq)
    assert t is not None and t.leaves() == leaves


@pytest.mark.parametrize("seq", ["⿰言", "⿰言俞俞", "⿳十罒", ""])
def test_parse_rejects_wrong_token_count(seq):
    """多一个少一个都不猜——错拆进词表比漏一个字贵。"""
    assert parse_ids(seq) is None


def test_primary_prefers_taiwan_then_default():
    alts = [("⿰忄彭", {"J"}), ("⿰𢜳彡", {"T"}), ("⿰忄彭", {"."})]
    assert pick_primary(alts) == "⿰𢜳彡"
    assert pick_primary([("A", {"J"}), ("B", {"."})]) == "B"
    assert pick_primary([("A", set()), ("B", set())]) == "A"


def test_structure_of_near_form_pair_differs_in_one_slot():
    """諭/論：同结构、左槽同、右槽不同——这正是「像素域摊薄、结构域离散」那一条。"""
    a, b = structure_of("諭"), structure_of("論")
    assert a.top == b.top == "⿰" and a.code == b.code == "⿰"
    assert a.top_slots()["L"] == b.top_slots()["L"] == ("言",)
    assert a.top_slots()["R"] != b.top_slots()["R"]


def test_single_component_char_has_no_slots():
    s = structure_of("人")
    assert s.top == SINGLE and s.leaves == ("人",)


def test_stop_set_expands_rare_compound_but_keeps_common_component():
    """言 是高频一级部件 → 叶；聽 罕见 → 拆开。词表就是这么长出来的。"""
    assert "言" in structure_of("諭").leaves
    assert "聽" not in structure_of("廳").leaves and "耳" in structure_of("廳").leaves


def test_index_query_semantics():
    idx = shared_index()
    hits = dict(idx.search(top="⿰", slots={"L": "言"}, components=["俞"], limit=2000))
    assert hits.get("諭") == 2                     # 左槽 + 部件 两条都中
    assert hits.get("論") == 1                     # 只中左槽
    assert "説" not in hits or hits["説"] == 1
    assert all(idx.struct[c].top == "⿰" for c in hits)   # top 是硬过滤
    # 只给部件、不给结构：跨结构召回
    comps = dict(idx.search(components=["鹿"], limit=5000))
    assert comps.get("麗") == 1 and comps.get("麓") == 1


def test_index_within_restricts_pool():
    idx = shared_index()
    got = idx.search(top="⿰", slots={"L": "言"}, within=["諭", "論", "麗"], limit=10)
    assert [c for c, _ in got] == ["論", "諭"] or [c for c, _ in got] == ["諭", "論"]


def test_component_consistency_none_means_no_opinion():
    probs = {"言": 0.9, "俞": 0.8, "侖": 0.1}
    out = component_consistency(["諭", "論", "人"], probs)
    assert out["諭"] == pytest.approx(0.85)
    assert out["論"] == pytest.approx(0.5)
    assert out["人"] is None                        # 一个部件都不在 probs 里 → 没意见，不是 0


def test_whole_table_parses_or_is_atomic():
    """全表 10 万行：非独体、非自指的主拆法必须能解析（表里的坏行要在这儿露头）。"""
    from open_guji_cv.clustering.ids_struct import _is_atomic
    tab = load_table()
    bad = [ch for ch, e in tab.items()
           if not _is_atomic(e.primary, ch) and parse_ids(e.primary) is None]
    assert len(bad) == 0, f"{len(bad)} 行主拆法解析失败，如 {bad[:10]}"


def test_struct_rerank_lifts_consistent_candidate_within_top_m():
    """融合表 [論, 諭, 人]，部件概率说右边是 俞 不是 侖 → 諭 该升到第一；
    人 没有部件（None）不进一致性表，但仍留在结果里；top_m 之外的字不动。"""
    order = ["論", "諭", "人", "麗"]
    probs = {"言": 0.9, "俞": 0.9, "侖": 0.05}
    out = struct_rerank(order, probs, k=4, weight=4.0, top_m=3)
    assert out[0] == "諭"
    assert set(out[:3]) == {"論", "諭", "人"}      # 前 top_m 名只重排不丢
    assert out[3] == "麗"                          # top_m 之外原样接回


def test_struct_rerank_is_identity_without_probs():
    assert struct_rerank(["論", "諭"], {}, k=2) == ["論", "諭"]
    # 一个候选都没有部件意见 → 原样
    assert struct_rerank(["人", "入"], {"言": 0.9}, k=2) == ["人", "入"]
