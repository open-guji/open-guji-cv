# -*- coding: utf-8 -*-
"""差异三层分类 + 按字对聚合（2026-09-22，用户定的框架）。

钉住四件事：
1. 避諱先认——不然 今→虜、金→褎 会散进 ③ 让人一对对判「谁错了」，而没一处是错的；
2. 人的结论优先于自动判据（`conventions` / `denied` 压过关系图与重复度）；
3. `denied`（人推翻的关系图边）必须把该对**退回 ③**，否则 治/冶 那类错边永远翻不了身；
4. 聚合无遗漏：各层条数之和 == 输入的可聚合差异数。
"""
from __future__ import annotations

from open_guji_cv.report.tiers import (BOOK_MIN, TIER_LABEL, pair_index,
                                       tier_counts, tier_of)


def _d(i, a, b, kind="sub.other", page=1):
    return {"id": f"b:{page}:1:{i}", "page": page, "col": 1, "slot": i, "sub": None,
            "kind": kind, "char": a, "ref": b, "hyp_ctx": "", "ref_ctx": "",
            "channel": None, "human": False}


def test_taboo_wins_over_everything():
    """避諱是版本学事实，比重复度、关系图都硬。"""
    assert tier_of("今", "虜", 1) == "taboo"
    assert tier_of("金", "褎", 2) == "taboo"


def test_book_convention_beats_graph_and_count():
    """人确认过的本书通例，出现 1 次也算 ②。"""
    assert tier_of("完", "元", 1, conventions={("完", "元")}) == "book"


def test_denied_edge_falls_back_to_dispute():
    """人推翻的关系图边退回逐对判——治/冶 那类错边靠这条翻身。"""
    assert tier_of("厯", "歷", 9) == "common"
    assert tier_of("厯", "歷", 9, denied={("厯", "歷")}) == "dispute"


def test_repeat_threshold_splits_book_and_dispute():
    assert tier_of("甲", "乙", BOOK_MIN) == "book"
    assert tier_of("甲", "乙", BOOK_MIN - 1) == "dispute"


def test_pair_index_aggregates_and_counts():
    diffs = [_d(i, "𠊓", "傍", page=i) for i in range(1, 25)] + [_d(1, "甲", "乙")]
    idx = pair_index(diffs)
    big = next(r for r in idx if r["pair"] == ["𠊓", "傍"])
    assert big["n"] == 24 and len(big["ids"]) == 24
    assert len(big["samples"]) == 3, "样例只留前 3 个，其余点开再取"
    assert len(big["pages"]) == 24


def test_nothing_is_lost_in_aggregation():
    diffs = ([_d(i, "𠊓", "傍", page=i) for i in range(1, 6)]
             + [_d(1, "今", "虜")] + [_d(2, "甲", "乙")])
    idx = pair_index(diffs)
    assert sum(r["n"] for r in idx) == len(diffs)
    c = tier_counts(idx)
    assert sum(v["items"] for v in c.values()) == len(diffs)
    assert set(c) == set(TIER_LABEL)


def test_gaps_are_not_aggregated():
    """增删没有「对应的另一个字」，聚合不了，报告里单独一档。"""
    diffs = [_d(1, "", "某", kind="missing"), _d(2, "某", "", kind="extra")]
    assert pair_index(diffs) == []


def test_dispute_sorts_first():
    """③ 排最前——要判谁错的才是人该先看的。"""
    diffs = [_d(i, "厯", "歷", page=i) for i in range(1, 10)] + [_d(1, "甲", "乙")]
    assert pair_index(diffs)[0]["tier"] == "dispute"
