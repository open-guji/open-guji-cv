# -*- coding: utf-8 -*-
"""文意 L2 表的强模型复核 `groups.l2_panel.panel_merge`：自造数据。"""
from __future__ import annotations

from open_guji_cv.groups.context import ctx_key
from open_guji_cv.groups.l2_panel import panel_merge

M = "己已巳"


def _t(**cells):
    return {"schema": "group_clf/1", "group": "jys", "ctx_ver": 3, "models": ["haiku"], "cells": cells}


def _e(ch, why, h):
    return {"ctx": ctx_key("左", "右"), "char": ch, "why": why, "votes": {"haiku": h}}


def a(ch, conf="high", why="x"):
    return {"char": ch, "conf": conf, "why": why}


def test_veto_when_strong_high_disagrees():
    t = _t(c1=_e("已", "agree", ["已", "high"]), c2=_e("已", "agree", ["已", "high"]), c3=_e("已", "agree", ["已", "high"]))
    n = panel_merge(t, {"opus": {"c1": a("己", why="附入己見"), "c2": a("己", "mid"), "c3": a("其他")}}, M)
    c = t["cells"]
    assert c["c1"]["char"] is None and c["c1"]["why"] == "abstain:panel_veto" and "附入己見" in c["c1"]["note"]
    assert c["c2"]["char"] == "已"                     # 强模型不是 high：不否决
    assert c["c3"]["char"] is None                     # high 的「其他」也否决
    assert n["veto"] == 2 and n["keep"] == 1


def test_fill_needs_strong_high_and_second_same_char():
    t = _t(c1=_e(None, "abstain:low_conf", ["已", "mid"]), c2=_e(None, "abstain:low_conf", ["已", "mid"]),
           c3=_e(None, "abstain:low_conf", ["已", "mid"]), c4=_e(None, "abstain:low_conf", ["己", "high"]),
           c5=_e(None, "abstain:other", ["其他", "low"]))
    runs = {"opus": {"c1": a("已"), "c2": a("已"), "c3": a("已", "mid"), "c4": a("已"), "c5": a("已")},
            "sonnet": {"c1": a("已", "low"), "c2": a("己"), "c3": a("已"), "c4": a("已"), "c5": a("已", "mid")}}
    n = panel_merge(t, runs, M)
    c = t["cells"]
    assert c["c1"]["char"] == "已" and c["c1"]["why"] == "agree:panel"     # 第二模型同字，置信不限
    assert c["c2"]["char"] is None                                          # 第二模型给别的字
    assert c["c3"]["char"] is None                                          # 强模型不是 high
    assert c["c4"]["char"] is None                                          # 主模型以 high 给过别的字
    assert c["c5"]["char"] == "已"
    assert c["c1"]["votes"] == {"haiku": ["已", "mid"], "opus": ["已", "high"], "sonnet": ["已", "low"]}
    assert n["panel"] == 2 and n["abstain"] == 3


def test_new_cells_get_ctx_key_and_votes():
    t = _t()
    runs = {"haiku": {"n1": a("巳"), "n2": a("已", "low"), "n3": a("己")},
            "opus": {"n1": a("巳"), "n2": a("已"), "n3": a("已")}, "sonnet": {"n2": a("已")}}
    ctxs = {"n1": ("x" * 25 + "辛", "朔"), "n2": ("書", "得"), "n3": ("人", "見")}
    n = panel_merge(t, runs, M, ctxs)
    c = t["cells"]
    assert c["n1"]["ctx"] == ctx_key("x" * 19 + "辛", "朔")                 # 窗口截到 20 字
    assert c["n1"]["char"] == "巳" and c["n1"]["why"] == "agree"
    assert c["n2"]["char"] == "已" and c["n2"]["why"] == "agree:panel"
    assert c["n3"]["char"] is None                                          # 主模型 high 但强模型 high 反对
    assert t["models"] == ["haiku", "opus", "sonnet"]
    assert n["new_main"] == 1 and n["panel"] == 1
