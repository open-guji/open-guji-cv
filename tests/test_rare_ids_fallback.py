# -*- coding: utf-8 -*-
"""IDS 兜底检索（`rare_panel.ids_fallback`）与候选结构字段（`struct_hint`）的回归。

只测无图那条路（结构约束 → 字集 → 命中数 + 频次排序）与修饰字段；有图那条
（emb 在池子里排序）要 checkpoint，contract 在 `test_cnn_candidates` 里管。
"""

from __future__ import annotations

from open_guji_cv.clustering.rare_panel import ids_fallback, struct_hint


def test_fallback_ranks_by_constraint_hits_then_returns_decorated_dicts():
    r = ids_fallback("⿰", {"L": "言"}, ["俞"], k=5)
    assert r and r[0]["char"] == "諭" and r[0]["score"] == 2.0      # 左槽 + 部件 两条都中
    assert all(d["score"] <= 2.0 for d in r)
    d = r[0]
    assert d["font"] == "ids" and d["ids"] and d["cp"] == "U+8AED"
    assert d["struct"] == {"top": "⿰", "slots": {"L": "言", "R": "俞"}}


def test_fallback_without_structure_recalls_across_structures():
    chars = [d["char"] for d in ids_fallback(None, None, ["鹿"], k=50)]
    assert "麗" in chars and "麓" in chars          # 基本区常用字不能被扩A 的字挤出前 50


def test_fallback_top_is_hard_filter_and_empty_query_is_empty():
    assert all(d["struct"]["top"] == "⿱" for d in ids_fallback("⿱", {"T": "林"}, ["鹿"], k=20))
    assert ids_fallback(None, None, [], k=5) == []


def test_struct_hint_single_component():
    assert struct_hint("人") == {"top": "独体", "slots": {}}
    assert struct_hint("諭")["slots"]["R"] == "俞"
