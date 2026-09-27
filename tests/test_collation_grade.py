# -*- coding: utf-8 -*-
"""对勘差异分层：「我们错了」vs「两个本子本来就不同」（2026-09-22）。

钉住三件事，都是分层敢不敢给人看的前提：
1. 避諱改字出现 1 次也算版本差异（靠字表，不靠统计）；
2. 重复度阈值是**全书**统计，不能按页算——同一字对散在 10 页各 1 次才是系统性的；
3. 只出现一两次、无已知关系的，必须落进 suspect，不能被悄悄归进「成果」那几层。

第 3 条是这层的安全性质：宁可多报存疑，不可把真错误藏进「版本差异」里说没事。
"""
from __future__ import annotations

from open_guji_cv.report.collation_grade import (REPEAT_MIN, SETTLED, TODO, adapt_diff,
                                                 grade, grade_pairs, summarize)


def _e(hyp, ref, kind="substitution", page=1):
    return {"hyp": hyp, "ref": ref, "kind": kind, "page": page}


def test_taboo_counts_as_version_difference_even_once():
    """避諱改字靠字表认，出现 1 次也不该进 suspect。"""
    es = [_e("金", "虜")]
    assert grade(es[0], grade_pairs(es)) == "taboo"


def test_repeated_pair_is_systematic():
    es = [_e("畱", "留", page=p) for p in range(REPEAT_MIN)]
    assert grade(es[0], grade_pairs(es)) == "systematic"


def test_rare_pair_stays_suspect():
    """只出现一两次、又不在字表里的，必须留在待覈档。"""
    es = [_e("甲", "乙")] * (REPEAT_MIN - 1)
    assert grade(es[0], grade_pairs(es)) == "suspect"


def test_repeat_is_counted_book_wide_not_per_page():
    """散在不同页各 1 次，合起来仍算系统性——这正是「系统性」的意思。"""
    es = [_e("畱", "留", page=p) for p in range(REPEAT_MIN)]
    assert len({e["page"] for e in es}) == REPEAT_MIN, "构造有误：应分布在不同页"
    assert grade(es[0], grade_pairs(es)) == "systematic"


def test_variant_and_gap_kinds_pass_through():
    es = [_e("厯", "歷", kind="variant"), _e("", "某", kind="missing"),
          _e("某", "", kind="extra")]
    pairs = grade_pairs(es)
    assert [grade(e, pairs) for e in es] == ["variant", "gap", "gap"]


def test_unreadable_is_suspect_not_gap():
    """转写成 □ 是我们没认出来，是待办，不是版本差异。"""
    es = [_e("□", "某", kind="unreadable")]
    assert grade(es[0], grade_pairs(es)) == "suspect"


def test_summarize_partitions_everything_exactly_once():
    es = ([_e("金", "虜")] + [_e("畱", "留", page=p) for p in range(REPEAT_MIN)]
          + [_e("甲", "乙")] + [_e("厯", "歷", kind="variant")])
    s = summarize(es)
    assert sum(s["counts"].values()) == len(es), "有条目被漏掉或重复计数"
    assert s["n_todo"] == 1 and s["n_settled"] == len(es) - 1


def test_settled_and_todo_do_not_overlap():
    assert not (set(SETTLED) & set(TODO))


def test_taboo_recognised_by_target_char():
    """避諱按**目标字**认：改法不固定，穷举字对永远漏。

    bxgb 实测同一个「虜」在不同处被刻成 金/國/今/乃/人/敵/改/因/彼/其…
    10 种以上。「整理本写虜、刻本写别的」这个模式本身就是避諱的定义。
    """
    for hyp in "金國今乃人敵改因彼其":
        e = _e(hyp, "虜")
        assert grade(e, grade_pairs([e])) == "taboo", f"{hyp}→虜"


def test_taboo_target_only_matches_witness_side():
    """只在整理本侧匹配——刻本刻了「虜」而整理本作别的字，那不是避諱。"""
    e = _e("虜", "甲")
    assert grade(e, grade_pairs([e])) != "taboo"


# ── adapt_diff：多证人 guji collate 的 Diff 形状 → 这里认的形状 ──────────
#
# `report/run.py::collate_book` 现在把这套判据接到 `report/collate.py::Diff`
# 上（原来只接单证人的旧脚本，见模块头「两个工具字段名不同」）。这几条钉住
# 字段翻译本身不能错——翻错了分层就是错的，但不会报错，只会悄悄分错层。

def _diff(kind, char, ref, *, human=False, page=1):
    """`asdict(Diff(...))` 的最小子集：`adapt_diff` 只读这几个键。"""
    return {"kind": kind, "char": char, "ref": ref, "human": human, "page": page}


def test_adapt_diff_maps_char_to_hyp():
    """`Diff.char` 是我们的字形，`grade()`/`grade_pairs()` 认的键叫 `hyp`。"""
    assert adapt_diff(_diff("sub.other", "甲", "乙"))["hyp"] == "甲"


def test_adapt_diff_collapses_substitution_kinds():
    """`sub.confusable`／`sub.other` 都是「不同字」，分层不分这两种。"""
    for k in ("sub.confusable", "sub.other"):
        assert adapt_diff(_diff(k, "甲", "乙"))["kind"] == "substitution"


def test_adapt_diff_collapses_variant_directions():
    """`variant.to_orthodox`／`variant.to_simp`／`variant.other` 三种方向都归 `variant`
    ——分层只问「是不是异体」，方向是另一层信息（html.py 单独显示）。"""
    for k in ("variant.to_orthodox", "variant.to_simp", "variant.other"):
        assert adapt_diff(_diff(k, "厯", "歷"))["kind"] == "variant"


def test_adapt_diff_passes_through_gap_and_unreadable():
    for k in ("missing", "extra", "unreadable"):
        assert adapt_diff(_diff(k, "甲", "乙"))["kind"] == k


def test_adapt_diff_source_reflects_human_flag():
    """`source` 只分「人裁」与「其余」——`grade()`/`_is_human()` 只关心是不是以
    `human` 结尾，不关心 `channel` 具体值，别在 adapter 里编 `auto:<channel>`。"""
    assert adapt_diff(_diff("sub.other", "甲", "乙", human=True))["source"] == "human"
    assert adapt_diff(_diff("sub.other", "甲", "乙", human=False))["source"] == ""


def test_adapt_diff_output_gradeable_end_to_end():
    """翻译完的形状能直接喂给 `grade()`，且结果跟直接用旧形状构造的一样。"""
    entries = [adapt_diff(_diff("sub.other", "金", "虜"))]
    assert grade(entries[0], grade_pairs(entries)) == "taboo"
