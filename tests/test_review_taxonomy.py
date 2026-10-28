# -*- coding: utf-8 -*-
"""review/taxonomy.py：待审格分类。自造单子里的格，不碰库和真书。"""
from __future__ import annotations

from open_guji_cv.review.taxonomy import BIG, SUBS, classify, conc_tag


def test_every_sub_belongs_to_a_known_big():
    assert all(v[0] in BIG for v in SUBS.values())


def test_cause_to_sub():
    k = lambda **c: classify(c).sub   # noqa: E731
    assert k(cause="A6") == "S1" and k(cause="A3") == "S2" and k(cause="A5") == "S3"
    assert k(cause="A2") == "P1" and k(cause=None, recheck=True) == "P2" and k(cause=None) == "U0"
    assert k(cause="F", cause_detail="浙") == "L1"
    assert k(cause="E", cause_detail="一/二") == "R1" and k(cause="G", cause_detail="冠/冦") == "R2"
    assert k(cause="Q") == "U0"


def test_occlusion_splits():
    assert classify({"cause": "D", "occ": {"ref_blank": True}}).sub == "O3"
    assert classify({"cause": "D", "ref": {"c": "〓"}}).sub == "O3"
    assert classify({"cause": "D", "occ": {"ref_blank": False}}).sub == "O2"
    assert classify({"cause": "D", "occ": {"ref_blank": False}}, occ_page_n=30).sub == "O1"
    assert classify({"cause": "D"}).sub == "O0"          # 瘦单


def test_group_and_pair_keys():
    g = {"曰": "ry"}.get
    z = classify({"cause": "C", "cause_detail": "group_flow_abstain,near_form", "ref": {"c": "曰"}}, group_of=g)
    assert (z.sub, z.key, z.owner) == ("Z1", "ry", "A24")
    assert classify({"cause": "C", "why": ["group_flow_ref_dissent"], "grp": "jys"}).sub == "Z2"
    assert classify({"cause": "C", "cause_detail": "near_form"}).key == "?"        # 瘦单没字组 id
    dec = lambda a, b: (a, b) == ("策", "䇿")   # noqa: E731
    assert classify({"cause": "B", "cause_detail": "策/䇿"}, decided=dec).sub == "M1"
    assert classify({"cause": "B", "cause_detail": "尙/尚"}, decided=dec) .sub == "M2"
    assert classify({"cause": "B", "cause_detail": "䇿/策"}, decided=dec).key == "䇿/策"


def test_h_i_reasons():
    assert classify({"cause": "H", "why": ["ctx_guard_ref"]}).key == "ctx_guard_ref"
    assert classify({"cause": "I", "ctx": {"c": ""}}).key == "ctx空"
    assert classify({"cause": "I", "ctx": {"c": "x"}}).key == "ctx有字"


def test_conc_tag():
    assert (conc_tag(20, 3), conc_tag(5, 6), conc_tag(3, 2)) == ("整页", "整列", "零散")
