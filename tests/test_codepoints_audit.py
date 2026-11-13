# -*- coding: utf-8 -*-
"""码位归一表入表审（scripts/codepoints_audit.py）：形近不同义的字不许进表。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import codepoints_audit as ca  # noqa: E402
from open_guji_cv.clustering.variants import never_group_pairs  # noqa: E402
from open_guji_cv.variants import VariantGraph  # noqa: E402


def _v(k, v):
    return ca.audit_one(k, v, VariantGraph.load(), never_group_pairs(), {})[0]


def test_near_form_and_never_group_rejected():
    assert _v("日", "曰") == "REJECT"      # 形近不同义组 ry
    assert _v("己", "已") == "REJECT"      # 形近不同义组 jys
    assert _v("刺", "剌") == "REJECT"      # 永不并组名单


def test_t2_needs_human_and_pure_t1_accepted():
    assert _v("撰", "𢰅") == "REVIEW"      # T2：字典互通，不自动收
    assert _v("刋", "刊") == "ACCEPT"      # T1，3 家异体来源


def test_chain_flagged():
    vg, ng = VariantGraph.load(), never_group_pairs()
    ver, _, why = ca.audit_one("刋", "刊", vg, ng, {"刊": "X"})
    assert ver == "REVIEW" and "链" in why
