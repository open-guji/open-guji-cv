# -*- coding: utf-8 -*-
"""审阅卡 → guji-proof 0.2 字段（GUJI-557）：只加字段、键序固定、空值不出。纯函数，不读任何产物。"""
from __future__ import annotations

from open_guji_cv.formats.proof_fields import pending_fields, slim_fields, why_codes

CARD = {
    "id": "vol01:9:7:17", "doubts": ["护栏:never_match", "库 unsure(cov=0.997)", "near_form", "ref_conflict"],
    "cls": "near_form", "ref": {"char": "臼", "op": "coord", "run": 1, "form": None},
    "db": {"verdict": "unsure", "cov": 0.99721, "wmax": 10.84,
           "candidates": [["曰", 0.99721], ["日", 0.98694], ["目", 0.9386], ["白", 0.9], ["自", 0.8], ["百", 0.7]]},
    "ocr": [["曰", 0.9], ["日", 0.1]], "stale_verdict": None, "occluded": None,
    "ctx": {"char": None, "margin": 0.1784, "source": "prior", "llm_suggestion": "曰"},
}


def test_full_card():
    f = pending_fields(CARD)
    assert f["why"] == ["near_form", "ref_conflict"]            # 中文说明与带冒号的不是码
    assert f["cls"] == "near_form" and "cls_sub" not in f
    assert f["lib_top"] == [{"c": "曰", "s": 0.9972}, {"c": "日", "s": 0.9869}, {"c": "目", "s": 0.9386},
                            {"c": "白", "s": 0.9}, {"c": "自", "s": 0.8}]   # ≤5、4 位小数
    assert f["lib"] == {"verdict": "unsure", "cov": 0.9972, "wmax": 10.8}
    assert f["conf"] == 0.9972 and f["margin"] == 0.1784
    assert f["ctx"] == {"c": "", "margin": 0.1784, "src": "prior"}          # 不带 llm_suggestion；没给字写 ""（字表 ctx.c 是字符串）
    assert f["ref"] == {"c": "臼", "op": "coord"}
    assert f["ocr"] == [{"c": "曰", "src": "ocr"}, {"c": "日", "src": "ocr"}]
    assert not {"stale", "occ", "img", "ex", "ctximg"} & set(f)


def test_no_codes_and_missing_parts():
    f = pending_fields({"id": "x", "doubts": ["库里没有这个字"], "db": None, "ctx": None, "ref": None})
    assert f == {"why": ["none"]}
    assert why_codes({"doubts": None}) == ["none"]


def test_stale_and_occluded():
    c = dict(CARD, cls="occluded", cls_sub="grid",
             stale_verdict={"verdict": {"shape": "日"}, "ts": "2026-10-01T10:00:00", "status": "rebound", "withdrawn": False},
             occluded={"char": "聖", "via": "coord", "ref_blank": True})
    f = pending_fields(c)
    assert f["stale"] == {"c": "日", "ts": "2026-10-01T10:00:00", "state": "rebound"}
    assert f["occ"] == {"c": "聖", "ref_blank": True} and f["cls_sub"] == "grid"
    w = pending_fields(dict(c, stale_verdict={"verdict": {"shape": "日"}, "ts": "t", "status": None, "withdrawn": True}))
    assert w["stale"]["state"] == "withdrawn"
    assert "stale" not in pending_fields(dict(c, stale_verdict={"verdict": {"shape": ""}, "ts": "t"}))   # 旧裁决=非字不预勾


def test_slim_only_three_keys():
    assert list(slim_fields(CARD)) == ["cls", "why", "conf"]
    assert slim_fields({"doubts": []}) == {"why": ["none"]}


def test_ctx_without_margin_is_omitted():
    f = pending_fields(dict(CARD, ctx={"char": "曰", "margin": None, "source": "context"}))
    assert "ctx" not in f and "margin" not in f
