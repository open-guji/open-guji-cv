# -*- coding: utf-8 -*-
"""IDS 反查：写出来的结构 Unicode 里有没有。"""

from open_guji_cv.clustering import ids_lookup as L


def test_exact_and_expanded():
    r = L.lookup("⿰言俞")
    assert r["hits"][0]["char"] == "諭" and r["hits"][0]["match"] == "exact"
    # 拆到笔画的写法也能认回同一个字
    deep = "".join(L.expand("⿰言俞"))
    assert L.encoded_match(deep) == ["諭"]


def test_near_prefers_one_component_diff():
    r = L.lookup("⿰言侖")
    assert r["hits"][0]["char"] == "論"
    near = [h for h in r["hits"] if h["match"] == "near"]
    assert near and all(h["diff"] <= 2 for h in near)


def test_reject_non_ids():
    assert L.lookup("言俞")["error"]
