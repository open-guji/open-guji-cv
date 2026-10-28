# -*- coding: utf-8 -*-
"""review/causes.py：待审格主成因码（GUJI-668）。自造 seed_admit／align_ref 片段，不碰真书。"""
from __future__ import annotations

import json

from open_guji_cv.review.causes import CAUSES, book_causes, causes_md, cause_of, doubt_codes, page_causes


def ch(cid="v:1:1:1", char="甲", doubts=(), **ev):
    return {"id": cid, "admit": False, "char": char, "doubts": list(doubts), "evidence": ev}


def test_doubt_codes_maps_prose():
    assert doubt_codes(["库 unsure(cov=0.977)", "上下文 margin 不足(0.49)", "replace_align", "库里没有这个字"]) == \
        {"lib_unsure", "上下文 margin 不足", "replace_align", "lib_miss"}


def test_priority_and_each_code():
    al = {"align_char": "乙", "align_op": "equal"}
    assert cause_of(ch(doubts=["occluded", "near_form"]), al, None, None)[0] == "D"
    assert cause_of(ch(char="已"), al, None, None)[0] == "C"                       # 己已巳族
    assert cause_of(ch(doubts=["group_flow_abstain"]), al, None, None)[0] == "C"
    assert cause_of(ch(), {"align_char": "〓"}, None, None)[0] == "A2"
    assert cause_of(ch(doubts=["ctx_garble_shape"]), None, None, None)[0] == "A6"
    assert cause_of(ch(), None, {"ref_char": ""}, None)[0] == "A1"
    assert cause_of(ch(), None, None, None, anchored=False)[0] == "A5"
    assert cause_of(ch(), None, None, "与现役对位冲突（…）")[0] == "A4"
    assert cause_of(ch(), None, None, "格数少于整理本字数（6 < 11）")[0] == "A3"
    assert cause_of(ch(doubts=["库里没有这个字"]), None, None, None)[0] == "F"
    assert cause_of(ch(), None, None, None)[0] == "A9"
    assert cause_of(ch(doubts=["ref_lib_variant"]), al, None, None) == ("B", "甲/乙")
    assert cause_of(ch(doubts=["context_vs_ref"]), al, None, None)[0] == "E"
    assert cause_of(ch(), {"align_char": "乙", "align_op": "replace"}, None, None)[0] == "G"
    assert cause_of(ch(char="乙"), al, None, None) == ("H", "乙")
    assert cause_of(ch(), al, None, None)[0] == "I"


def test_page_and_book_causes(tmp_path):
    seed = {"columns": [{"chars": [
        {"id": "v:1:1:1", "admit": True, "char": "甲"},
        {"id": "v:1:1:2", "admit": False, "doubts": ["excluded"]},
        ch("v:1:1:3"),
        ch("v:1:2:1")]}]}
    align = {"anchored": True, "chars": [{"id": "v:1:1:3", "align_char": "乙", "align_op": "equal"}],
             "coord": [], "coord_fallback": {"2": "格数少于整理本字数（1 < 10）"}}
    assert page_causes(seed, align) == {"v:1:1:3": ("I", "甲/乙"), "v:1:2:1": ("A3", "格数少于整理本字数（1 < 10）")}
    for step, doc in (("seed_admit", seed), ("align_ref", align)):
        d = tmp_path / "v" / step
        d.mkdir(parents=True)
        (d / "p0001.json").write_text(json.dumps({step: doc}, ensure_ascii=False), encoding="utf-8")
    res = book_causes(tmp_path, "v")
    assert res == {"1:1:3": {"cause": "I", "detail": "甲/乙", "refc": "乙"},
                   "1:2:1": {"cause": "A3", "detail": "格数少于整理本字数（1 < 10）"}}
    md = causes_md("v", res)
    assert "| A3 |" in md and CAUSES["A3"][1] in md and "50%" in md
