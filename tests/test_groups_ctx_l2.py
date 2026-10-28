"""文意 L2 模型（`groups/ctx_l2`）：小头推理、门槛与护栏、方法数组里只补 L3 表没答案的格。编码器用假的，不装 torch 也能跑。"""
import json

from open_guji_cv.groups import ctx_l2
from open_guji_cv.groups.methods import CtxModel, Chain, CtxRule, Llm, MethodInput

FEAT = "日曰目己已巳"


class FakeEnc:
    """向量 2 维：左邻是「乙」→ 偏曰，否则偏日；填空分按 `lp` 给。"""

    def __init__(self, lp=None):
        self.lp = lp or {c: -1.0 for c in "日曰目己已巳"}
        self.calls = 0

    def encode(self, left, right, chars):
        self.calls += 1
        h = [1.0, 0.0] if left.endswith("乙") else [0.0, 1.0]
        return h, {c: self.lp.get(c, -10.0) for c in chars}


def head(**kw):
    d = {"schema": ctx_l2.SCHEMA, "group": "ry", "ver": "ry-l2m-t", "encoder": {"name": "x"}, "feat_chars": FEAT,
         "classes": ["日", "曰", "其他"], "mean": [0.0] * 8, "scale": [1.0] * 8,
         # 维 0（左邻乙）→ 曰；维 1 → 日；其他类压低
         "coef": [[0, 20, 0, 0, 0, 0, 0, 0], [20, 0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0, 0, 0]],
         "intercept": [0.0, 0.0, -30.0], "thr": 0.99, "other": {"chars": "自", "d": -3.0}}
    d.update(kw)
    return d


def test_predict_and_threshold():
    v = ctx_l2.judge(head(), "某乙", "學而", frozenset("日曰"), FakeEnc())
    assert (v.char, v.why, v.via) == ("曰", "agree", "ctx_l2") and v.conf > 0.99
    v = ctx_l2.judge(head(thr=0.999999999999), "某乙", "學而", frozenset("日曰"), FakeEnc())
    assert v.char is None and v.why == "abstain:low_p"


def test_other_form_guard():
    """填空分上组外形近字（自）与所判字差不到 d → 弃权（「斷自陶唐」）。"""
    v = ctx_l2.judge(head(), "斷", "陶唐", frozenset("日曰"), FakeEnc({"日": -1.0, "自": -2.0}))
    assert v.char is None and v.why == "abstain:other_form"
    v = ctx_l2.judge(head(), "斷", "陶唐", frozenset("日曰"), FakeEnc({"日": -1.0, "自": -9.0}))
    assert v.char == "日"


def test_right_only():
    """己已巳：右邻是地支（丑卯巳未酉亥）只许判「己」。"""
    h = head(classes=["已", "己", "其他"], right_only={"丑卯巳未酉亥": "己"})
    assert ctx_l2.judge(h, "不利", "未博學", frozenset("己已巳"), FakeEnc()).why == "abstain:right_only"
    assert ctx_l2.judge(h, "不利", "博學", frozenset("己已巳"), FakeEnc()).char == "已"


def test_other_class_is_abstain_other_high():
    h = head(intercept=[0.0, 0.0, 50.0])
    v = ctx_l2.judge(h, "窠", "葢其", frozenset("日目"), FakeEnc())
    assert v.char is None and v.why == "abstain:other" and v.extra["other_conf"] == "high"


def test_no_encoder(monkeypatch):
    monkeypatch.setattr(ctx_l2, "_encoder", lambda n, r: None)
    assert ctx_l2.judge(head(), "某乙", "", frozenset("日曰"), None).why == "abstain:no_encoder"


def test_chain_fills_only_table_gaps(tmp_path, monkeypatch):
    """方法数组：L3 表有答案 → 不跑模型；表缺格 → 模型补；表里大模型说「其他」→ 不补。"""
    monkeypatch.setattr(ctx_l2, "_encoder", lambda n, r: FakeEnc())
    hp = tmp_path / "ry.json"
    hp.write_text(json.dumps(head(), ensure_ascii=False), encoding="utf-8")
    from open_guji_cv.groups.context import ctx_key
    tp = tmp_path / "l3.json"
    tp.write_text(json.dumps({"schema": "group_clf/1", "group": "ry", "ctx_ver": 3, "ver": "t", "models": ["haiku"], "cells": {
        "v:1:1:1": {"ctx": ctx_key("某某", "云"), "char": "日", "why": "agree", "votes": {"haiku": ["日", "high"]}},
        "v:1:1:2": {"ctx": ctx_key("某乙", "云"), "char": None, "why": "abstain:other", "votes": {"haiku": ["其他", "high"]}},
    }}, ensure_ascii=False), encoding="utf-8")

    class Cfg:
        l2_tables = {"ry": str(tp)}
        l2_models = {"ry": str(hp)}
        canon = None
        l2_drift = 0

    chain = Chain("ctx", steps=(CtxRule(), Llm(), CtxModel()))

    def run(cid, left, right):
        return chain.run(MethodInput(group="ry", members=frozenset("日曰"), cell_id=cid, cands=[], ref=None, cfg=Cfg(),
                                     left=left, right=right))
    v = run("v:1:1:1", "某某", "云")
    assert v.char == "日" and v.via == "ctx:ctx_l3"
    v = run("v:1:1:2", "某乙", "云")
    assert v.char is None and v.why == "abstain:other" and v.via == "ctx:ctx_l3"
    v = run("v:1:1:3", "某乙", "云")
    assert v.char == "曰" and v.via == "ctx:ctx_l2" and v.extra["p"] > 0.99
