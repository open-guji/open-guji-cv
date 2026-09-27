# -*- coding: utf-8 -*-
"""`config/confusable_human.json` 里「按形区分」四对（字形库 11 §〇，2026-09-27）：
强/強、却/卻、回/囘、并/幷——两形能分、认错算错，靠 `HUMAN_TABLE` 给匹配侧
拉警报。别/內、内/內是「书级指定」类，不进这张表（进 `BookSpec.codepoints`，
见 `tests/test_book_codepoints.py`），本文件顺带守住两类没被混进同一张表。
"""

from __future__ import annotations

import json

from open_guji_cv.clustering import confusable as cf

_NEW_PAIRS = [("强", "強"), ("却", "卻"), ("回", "囘"), ("并", "幷")]
_BOOK_LEVEL_PAIRS = [("别", "別"), ("内", "內")]   # 书级指定类，不该出现在本表


def test_table_is_valid_json_with_consistent_keys():
    d = json.loads(cf.HUMAN_TABLE.read_text(encoding="utf-8"))
    assert set(d["hits"]) <= set(d["pairs"])
    assert set(d["witnesses"]) <= set(d["pairs"])
    assert d["n_pairs"] == len(d["pairs"])


def test_shape_split_pairs_present_and_recognized():
    cf.partners.cache_clear()
    partners = cf.partners(tau=None)   # tau=None：只看手工表 + 人裁表，不掺字体表
    for a, b in _NEW_PAIRS:
        assert b in partners.get(a, frozenset()), f"{a}/{b} 该在人裁形近表里互认对手"
        assert a in partners.get(b, frozenset())


def test_book_level_pairs_are_not_in_the_shape_table():
    """别/內、内/內按书统一码位，不是「形状分得开但会混」——不该进 HUMAN_TABLE。"""
    d = json.loads(cf.HUMAN_TABLE.read_text(encoding="utf-8"))
    keys = set(d["pairs"])
    for a, b in _BOOK_LEVEL_PAIRS:
        assert a + b not in keys and b + a not in keys


def test_new_pairs_have_provenance_round():
    d = json.loads(cf.HUMAN_TABLE.read_text(encoding="utf-8"))
    rounds = d["rounds"]["codepoint_shape_split_r1"]
    assert set(rounds["pairs"]) == {"强強", "却卻", "回囘", "并幷"}
