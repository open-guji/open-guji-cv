# -*- coding: utf-8 -*-
"""scripts/zhengli/vision_ask.py（看图交外部模型，GUJI-665）：只测解析、合并、计分，不联网。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "zhengli" / "vision_ask.py"
spec = importlib.util.spec_from_file_location("zhengli_vision_ask", SCRIPT)
va = importlib.util.module_from_spec(spec)
spec.loader.exec_module(va)


def test_parse_answer_skips_think_and_noise():
    t = '<think>想想 {"v": "ok"} 不算</think>\n答：{"v": "wrong", "char": "己", "note": "知己"}'
    assert va.parse_answer(t) == {"v": "wrong", "char": "己", "note": "知己"}
    assert va.parse_answer("看不出来") is None
    assert va.parse_answer('{"v": "maybe"}') is None


def test_prompt_mentions_char_witness_ctx():
    p = va.prompt_for({"char": "已", "witness": {"四库光盘版": "己"}, "ctx": "恭【已】無爲"})
    assert "「已」" in p and "四库光盘版作「己」" in p and "恭【已】無爲" in p


def r(cell, v, judge, char=None):
    return {"cell": cell, "v": v, "judge": judge, "shown": "甲", "ts": "t", **({"char": char} if char else {})}


def test_merge_only_agreement_counts():
    a = {c: r(c, v, "s", ch) for c, v, ch in [("1", "ok", None), ("2", "wrong", "乙"), ("3", "ok", None), ("4", "wrong", "乙"), ("5", "ok", None)]}
    b = {c: r(c, v, "m", ch) for c, v, ch in [("1", "ok", None), ("2", "wrong", "乙"), ("3", "wrong", "丙"), ("4", "wrong", "丁")]}
    m = va.merge(a, b)
    assert {c: x["v"] for c, x in m.items()} == {"1": "ok", "2": "wrong", "3": "unsure", "4": "unsure", "5": "ok"}
    assert m["2"]["char"] == "乙" and "两家不一致" in m["3"]["note"] and m["5"]["judge"] == "s"


def test_score(tmp_path):
    ref = {c: r(c, v, "s") for c, v in [("1", "ok"), ("2", "wrong"), ("3", "ok")]}
    hyp = {c: r(c, v, "m") for c, v in [("1", "ok"), ("2", "ok"), ("3", "wrong")]}
    assert va.score(ref, hyp) == {"n": 3, "agree": 1, "missed_wrong": ["2"], "false_wrong": ["3"], "hyp_unsure": 0}
    f = tmp_path / "x.jsonl"
    f.write_text(json.dumps(ref["1"]) + "\n\n", encoding="utf-8")
    assert list(va.read_jsonl(f)) == ["1"]
