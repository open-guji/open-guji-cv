# -*- coding: utf-8 -*-
"""字组判别后端适配器（`open_guji_cv/groups/backends.py`，S0）。自造数据与桩模型，不读真书。

重点：适配器必须与它包住的现有函数**逐格一致**——`JysRuleBackend`／`CtxTableBackend` 对拍各自的 utils 函数。
`GroupClfTableBackend` 原先对拍 `steps.group_decide.lookup`；Step6b `group_decide` 已于 2026-10-18 删除
（sheldon 定），改成对着当时对拍过的逐格答案写死期望值。
"""
from __future__ import annotations

import json

import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401
import open_guji_cv.utils.rr_clf as rr
from open_guji_cv.groups import GROUPS, JudgeInput, PatchUnavailable, window_from_text
from open_guji_cv.groups.backends import (CtxTableBackend, GroupClfTableBackend, JysRuleBackend,
                                          RrImageBackend)
from open_guji_cv.utils import ji_yi_si_clf
from open_guji_cv.utils.ji_yi_si_clf import ctx_key


def _cell(cid="b:1:1:2", ref="日", left="", right="", patch=None):
    return JudgeInput(id=cid, ref=ref, window=window_from_text(left, right), patch=patch)


# ---------------------------------------------------------------- 窗口
def test_window_from_text_truncates_and_handles_zero():
    w = window_from_text("甲乙丙丁", "戊己庚辛")
    assert w(2) == ("丙丁", "戊己")             # 左取靠近目标的末尾、右取靠近目标的开头
    assert w(30) == ("甲乙丙丁", "戊己庚辛")
    assert w(0) == ("", "") and w(-1) == ("", "")


# ---------------------------------------------------------------- jys 规则路
@pytest.mark.parametrize("left,right", [("甲", ""), ("而", ""), ("", "年"), ("自", ""), ("无关紧要字", "无关"), ("而", "易"), ("", "")])
def test_jys_rule_backend_equals_classify(left, right):
    spec = GROUPS["jys"]
    v = JysRuleBackend().judge(spec, _cell(left=left, right=right))
    ch, why = ji_yi_si_clf.classify(left, right)
    assert v.char == ch and v.via == "rule"
    assert v.why == ("agree" if ch else "abstain:rule")
    # 与现行 `_ji_yi_si_clf_cell` 写进 evidence 的两块结构一致（没有表／llm 路时）
    assert v.extra["clf_ev"] == {"rule": ch, "why": why, "via": "rule" if ch else None}
    assert v.extra["ji_yi_si"] == {"char": ch, "why": why}


# ---------------------------------------------------------------- group_clf/1 表：逐格答案（原与 group_decide.lookup 对拍）
def _gc_table(group, cells, schema="group_clf/1"):
    return {"schema": schema, "group": group, "cells": cells}


_GC_EXPECT_OK = {
    "hit": ("日", 0.9, "agree"),
    "abstain": (None, None, "abstain:muse"),
    "outside": (None, 0.5, "agree"),          # 组外字 → 弃权，conf 原样
    "badctx": (None, None, "ctx_mismatch"),
    "missing": (None, None, "cache_miss"),
}


def test_group_clf_backend_verdicts():
    left, right = "而", "易"
    key = ctx_key(left, right, 30)
    cells = {
        "hit": {"ctx": key, "char": "日", "conf": 0.9, "why": "agree", "votes": {"muse": ["日", "日"]}},
        "abstain": {"ctx": key, "char": None, "conf": None, "why": "abstain:muse"},
        "outside": {"ctx": key, "char": "天", "conf": 0.5, "why": "agree"},      # 组外字 → 弃权
        "badctx": {"ctx": "0000", "char": "曰", "why": "agree"},
    }
    mismatch = {cid: (None, None, "ver_mismatch") for cid in _GC_EXPECT_OK}
    for table, group, expect in [(_gc_table("ry", cells), "ry", _GC_EXPECT_OK),
                                 (_gc_table("ry", cells, schema="other/1"), "ry", mismatch),
                                 (_gc_table("jys", cells), "ry", mismatch)]:
        be = GroupClfTableBackend(table)
        for cid, want in expect.items():
            new = be.judge(GROUPS[group], _cell(cid=cid, left=left, right=right))
            assert (new.char, new.conf, new.why) == want, (cid, table["schema"], table["group"])


def test_group_clf_backend_keeps_votes_in_extra():
    key = ctx_key("", "", 30)
    table = _gc_table("ry", {"c": {"ctx": key, "char": "曰", "why": "agree", "votes": {"muse": ["曰", "曰"]}}})
    v = GroupClfTableBackend(table).judge(GROUPS["ry"], _cell(cid="c"))
    assert v.extra["votes"] == {"muse": ["曰", "曰"]}


def test_group_clf_backend_from_file_has_fingerprint(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(_gc_table("ry", {})), encoding="utf-8")
    be = GroupClfTableBackend(p)
    assert len(be.fingerprint) == 16
    p.write_text(json.dumps(_gc_table("ry", {"x": {}})), encoding="utf-8")
    assert GroupClfTableBackend(p).fingerprint != be.fingerprint        # 表一变指纹变


# ---------------------------------------------------------------- jys 语料决策表
def test_ctx_table_backend_uses_2char_window_and_stops_at_unknown(tmp_path):
    p = tmp_path / "ctx.json"
    p.write_text(json.dumps({"keys": {"10|而|": [0, 10, 0], "10|甲|": [3, 3, 3]}}), encoding="utf-8")
    be = CtxTableBackend(purity=0.98, min_n=5, path=p)
    spec = GROUPS["jys"]
    v = be.judge(spec, _cell(left="前文而", right=""))
    assert (v.char, v.why, v.via) == ("已", "agree", "ctx_table")
    assert be.judge(spec, _cell(left="乙甲", right="")).char is None          # 不纯 → 弃权
    # 左窗口里碰到 □ 就停：「甲□而」只认「而」，不跨过空位拼接
    assert be.judge(spec, _cell(left="甲□而", right="")).char == "已"
    assert len(be.fingerprint) == 16


# ---------------------------------------------------------------- rr 图像模型
def test_rr_image_backend_wraps_classify_and_never_silently_skips(monkeypatch):
    be = RrImageBackend(p_thr=0.5)
    spec = GROUPS["rr"]
    monkeypatch.setattr(rr, "classify", lambda gray, model, p: {"probs": {"人": 0.1, "入": 0.8, "八": 0.05, "其他": 0.05},
                                                               "pick": "入", "gated": False, "p": 0.8})
    gray = np.zeros((8, 8), np.uint8)
    v = be.judge(spec, _cell(patch=lambda: gray))
    assert (v.char, v.conf, v.why, v.via) == ("入", 0.8, "agree", "image")
    assert v.extra["legacy"]["pick"] == "入"
    # 缺图：后端抛 PatchUnavailable，由调用方按 skip／raise 留痕——不静默弃权
    with pytest.raises(PatchUnavailable):
        be.judge(spec, _cell(patch=None))
    # 弃权原因：质量闸 vs 概率太低
    monkeypatch.setattr(rr, "classify", lambda g, m, p: {"probs": None, "pick": None, "gated": True, "p": 0.0})
    assert be.judge(spec, _cell(patch=lambda: gray)).why == "abstain:gated"
    monkeypatch.setattr(rr, "classify", lambda g, m, p: {"probs": {}, "pick": None, "gated": False, "p": 0.3})
    assert be.judge(spec, _cell(patch=lambda: gray)).why == "abstain:low_p"
