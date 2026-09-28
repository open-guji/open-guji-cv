# -*- coding: utf-8 -*-
"""IDS 结构层（`clustering/ids_struct.py`，M0 第一块）的回归。

钉住四件事：解析器对元数/无码部件的处理、主拆法的 T 优先、停集展开给出的
槽位部件、倒排索引的查询语义。**不测重排效果**——`component_consistency`
只是函数，接不接进 RRF 要等靶子量过（设计稿 §11 #3）。
"""

from __future__ import annotations

import pytest

from open_guji_cv.clustering.ids_struct import (IDC, SINGLE, IdsIndex, Node,
                                                STRUCT_CLASSES, build_slot_labels,
                                                component_consistency, slot_keys_of,
                                                struct_index, struct_rerank,
                                                load_table, parse_ids,
                                                pick_primary, shared_index,
                                                structure_of, tokenize,
                                                atom_multiset, atom1_pairs,
                                                build_confusable_pairs,
                                                confusable_detail, is_confusable,
                                                first_level_freq,
                                                leaf_multiset, load_confusable_pairs,
                                                sameleaf_pairs, slot1_pairs,
                                                write_confusable_pairs)


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


def test_step_a_label_space():
    """结构头 18 类、槽位标签 `部件@槽`；独体字是 `字@S`；词表按 ≥min_count 过滤。"""
    assert len(STRUCT_CLASSES) == 18 and STRUCT_CLASSES[-1] == SINGLE
    assert STRUCT_CLASSES[struct_index("諭")] == "⿰" and STRUCT_CLASSES[struct_index("人")] == SINGLE
    assert slot_keys_of("諭") == ("言@L", "俞@R") and slot_keys_of("人") == ("人@S",)
    labels = build_slot_labels(["諭", "論", "記", "計", "人"], min_count=2)
    assert "言@L" in labels and "俞@R" not in labels and "人@S" not in labels
    # 槽位概率能直接喂给 struct_rerank
    out = struct_rerank(["論", "諭"], {"言@L": 0.9, "俞@R": 0.9, "侖@R": 0.1},
                        components_of=slot_keys_of, k=2, weight=4.0)
    assert out[0] == "諭"


# ── 形近对表（overview#128）──────────────────────────────────────────

def test_leaf_multiset_keeps_duplicates():
    """`leaves` 元组去重，`leaf_multiset` 不去重——同一部件在两个槽位各出现
    一次要记两次，供 atom1/sameleaf 的多重集比较用。"""
    m = leaf_multiset("金")     # ⿻(全, 丷)，全 本身再拆出一个 王 里的一
    assert sum(m.values()) == len(structure_of("金", 20).slots)


def test_slot1_pairs_catch_one_slot_difference():
    """令/今：同结构、同槽位路径，只有 B 槽不同——最常见的一档，score 恒为
    (槽数-1)/槽数（这里 3 槽 = 2/3）。申/中 是 2 槽的典型（score 0.5）。"""
    pairs = slot1_pairs(["令", "今", "申", "中", "人"])
    assert ("今", "令") in pairs and pairs[("今", "令")].score == pytest.approx(2 / 3)
    assert ("中", "申") in pairs and pairs[("中", "申")].score == pytest.approx(0.5)
    # 独体字（人）没有槽位，不会跟任何人配对
    assert not any("人" in p for p in pairs)


def test_slot1_pairs_max_shared_freq_only_filters_2_slot_structures():
    """`max_shared_freq` 按共享部件的一级频次筛 2 槽结构：冶/治 共享「台」是
    冷僻声旁（频次远低于门槛），门槛再低也留着；申/中 共享「丨」频次高得多，
    门槛卡在两者中间时该被筛掉但冶/治仍在。3 槽的令/今不受这个参数影响。"""
    freq = first_level_freq()
    lo = freq.get("台", 0) + 1                 # 刚好挡住比「台」更常见的共享部件
    pairs_lo = slot1_pairs(["冶", "治", "申", "中", "令", "今"], max_shared_freq=lo)
    assert ("冶", "治") in pairs_lo
    assert ("中", "申") not in pairs_lo if freq.get("丨", 0) > lo else True
    assert ("今", "令") in pairs_lo             # 3 槽不受影响
    # 不传参数＝不过滤，行为与旧版一致
    pairs_all = slot1_pairs(["冶", "治", "申", "中"])
    assert ("冶", "治") in pairs_all and ("中", "申") in pairs_all


def test_slot1_pairs_reject_different_skeleton():
    """结构或槽位路径数不同就不算——王(2槽)与玉(3槽) 不该被 slot1 抓到
    （它们的真实关系是 atom1，见下）。"""
    pairs = slot1_pairs(["玉", "王"])
    assert ("王", "玉") not in pairs and not pairs


def test_atom1_pairs_catch_one_stroke_add():
    """天=大+一、玉=王+丶：K=20 口径下结构对不上，但笔画级原子恰好差一个。"""
    pairs = atom1_pairs(["天", "大", "玉", "王"])
    assert ("大", "天") in pairs
    assert pairs[("大", "天")].detail.endswith("一")
    assert ("玉", "王") in pairs
    assert pairs[("玉", "王")].detail.endswith("丶")


def test_atom1_pairs_reject_distance_two():
    """仕=士+亻，亻 本身是 2 个原子（丿+丨）——原子距离是 2，不是「恰好一个」，
    不该进 atom1（严格按 N2 文档的「差一个笔画级原子」，不放宽）。"""
    pairs = atom1_pairs(["仕", "士"])
    assert ("仕", "士") not in pairs and ("士", "仕") not in pairs


def test_sameleaf_pairs_need_same_multiset_different_structure():
    pairs = sameleaf_pairs(["諭", "論", "人"])
    assert not pairs        # 諭/論 是 slot 类不是 sameleaf 类（结构相同）


def test_build_confusable_pairs_dedups_and_prefers_higher_score():
    """同一对可能被多个类命中（冶/治 是最典型的例子：K=20 下是 slot，
    在这个小字表里恰好也满足 atom1）——只留分高的一条。"""
    pairs = {(p.a, p.b): p for p in build_confusable_pairs(["冶", "治"])}
    assert ("冶", "治") in pairs
    cp = pairs[("冶", "治")]
    assert cp.kind in ("slot", "atom1") and cp.score > 0


def test_known_miss_pure_atomic_chars_and_pure_style_confusion():
    """已知接不住的两类，钉死别误判成回归：己/已/巳 三字本身是独体（无 IDS
    可拆），以/取 部件与结构完全无关——三类判据都该给出「不是形近对」。"""
    pairs = build_confusable_pairs(["己", "已", "巳", "以", "取", "人", "入"])
    got = {(p.a, p.b) for p in pairs} | {(p.b, p.a) for p in pairs}
    for a, b in [("己", "已"), ("已", "巳"), ("己", "巳"), ("以", "取"), ("人", "入")]:
        assert (a, b) not in got, f"{a}/{b} 不该被判成形近对（已知的方法论边界）"


def test_write_and_load_confusable_pairs_roundtrip(tmp_path):
    pairs = build_confusable_pairs(["令", "今", "申", "中", "天", "大"])
    out = write_confusable_pairs(pairs, tmp_path / "ids_confusable_pairs_v1.tsv")
    load_confusable_pairs.cache_clear()
    table = load_confusable_pairs(str(out))
    assert len(table) == len(pairs)
    assert frozenset(("今", "令")) in table
    load_confusable_pairs.cache_clear()


def test_is_confusable_and_confusable_detail(tmp_path):
    pairs = build_confusable_pairs(["令", "今", "天", "大"])
    out = write_confusable_pairs(pairs, tmp_path / "t.tsv")
    load_confusable_pairs.cache_clear()
    path = str(out)
    assert is_confusable("今", "令", path) and is_confusable("令", "今", path)
    assert not is_confusable("今", "今", path)          # 自己不算
    assert not is_confusable("今", "人", path)          # 表里没有
    detail = confusable_detail("大", "天", path)
    assert detail is not None and detail.kind == "atom1"
    load_confusable_pairs.cache_clear()


def test_is_confusable_defaults_to_empty_table_when_file_missing():
    load_confusable_pairs.cache_clear()
    assert not is_confusable("今", "令", "/no/such/confusable_pairs.tsv")
    load_confusable_pairs.cache_clear()
