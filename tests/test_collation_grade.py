# -*- coding: utf-8 -*-
"""对勘差异分层：「我们错了」vs「两个本子本来就不同」（2026-09-22）。

钉住三件事，都是分层敢不敢给人看的前提：
1. 避諱改字出现 1 次也算版本差异（靠字表，不靠统计）；
2. 重复度阈值是**全书**统计，不能按页算——同一字对散在 10 页各 1 次才是系统性的；
3. 只出现一两次、无已知关系的，必须落进 suspect，不能被悄悄归进「成果」那几层。

第 3 条是这层的安全性质：宁可多报存疑，不可把真错误藏进「版本差异」里说没事。
"""
from __future__ import annotations

from open_guji_cv.report.collation_grade import (REPEAT_MIN, SETTLED, TODO, grade,
                                                 grade_pairs, summarize)


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
