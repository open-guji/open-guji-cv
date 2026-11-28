"""书级部件刻形判法（`groups.part_shape`，全唐文 11-15）：截部件、多对、门槛与弃权、seed_admit 接线。
数据与权重全在测试里造，不读真书数据。"""
from __future__ import annotations

import base64
import json

import cv2
import numpy as np

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.groups import part_shape as P
from open_guji_cv.groups import wu_shape as W
from open_guji_cv.steps import seed_admit as sa
from open_guji_cv.steps.seed_admit import SeedAdmitParams

SHAPES = {"f.0.weight": (16, 1, 3, 3), "f.0.bias": (16,), "f.3.weight": (32, 16, 3, 3), "f.3.bias": (32,),
          "f.6.weight": (64, 32, 3, 3), "f.6.bias": (64,), "f.11.weight": (64, 4096), "f.11.bias": (64,),
          "f.13.weight": (1, 64), "f.13.bias": (1,)}


def _enc(a):
    return {"shape": list(a.shape), "dtype": "<f4", "b64": base64.b64encode(np.ascontiguousarray(a, "<f4").tobytes()).decode()}


def _net(bias=0.0, zero=False, seed=0):
    rng = np.random.default_rng(seed)
    net = {k: (np.zeros(s, np.float32) if zero else rng.normal(0, 0.05, s).astype(np.float32)) for k, s in SHAPES.items()}
    net["f.13.bias"] = np.array([bias], np.float32)
    if bias:
        net["f.13.weight"] = np.zeros((1, 64), np.float32)
    return net


def _model_file(tmp_path, pairs, name="part_shape.json"):
    f = tmp_path / name
    f.write_text(json.dumps({"schema": P.SCHEMA, "pairs": [
        {"chars": list(ch), "box": box, "size": 64, "t": t, "nets": [{k: _enc(v) for k, v in net.items()}]}
        for ch, box, t, net in pairs]}), encoding="utf-8")
    return f


def _glyph():
    """左边一个方框，右边一竖一横。"""
    g = np.full((120, 120), 255, np.uint8)
    cv2.rectangle(g, (8, 10), (50, 60), 0, 4)
    cv2.line(g, (80, 10), (80, 110), 0, 5)
    cv2.line(g, (70, 90), (110, 90), 0, 5)
    return g


def test_prep_crops_the_box_and_matches_wu_forward(tmp_path):
    g = _glyph()
    left = P.prep(g, (0, 0.5, 0, 1))
    right = P.prep(g, (0.5, 1, 0, 1))
    assert left.shape == (64, 64) and not np.array_equal(left, right)
    net = _net()
    f = _model_file(tmp_path, [(("剌", "刺"), [0, 0.5, 0, 1], 0.95, net)])
    pr = P.load(str(f))["pairs"][0]
    assert abs(P.prob(g, pr) - W._forward(net, left)) < 1e-6          # 前向与 wu_shape 共用
    assert P.prep(np.full((80, 80), 255, np.uint8), (0, 1, 0, 1)) is None


def test_threshold_abstain_and_pair_lookup(tmp_path):
    g = _glyph()
    f = _model_file(tmp_path, [(("剌", "刺"), [0, 0.65, 0, 1], 0.95, _net(bias=8.0)),
                               (("疎", "踈"), [0, 0.5, 0, 0.6], 0.95, _net(bias=-8.0)),
                               (("攢", "攅"), [0, 1, 0, 1], 0.95, _net(zero=True))])
    m = P.load(str(f))
    assert m["_chars"] == frozenset("剌刺疎踈攢攅")
    assert P.pair_of(m, "x") is None
    assert P.judge(g, P.pair_of(m, "剌"))["char"] == "刺"          # p≈1 → chars[1]
    assert P.judge(g, P.pair_of(m, "踈"))["char"] == "疎"          # p≈0 → chars[0]
    v = P.judge(g, P.pair_of(m, "攅"))
    assert v["char"] is None and v["why"] == "abstain:low_p" and v["pair"] == "攢攅"
    assert P.judge(np.full((80, 80), 255, np.uint8), P.pair_of(m, "剌")) == {"char": None, "why": "abstain:no_ink", "pair": "剌刺"}
    assert P.fingerprint(str(f)) and P.fingerprint(str(tmp_path / "nope.json")) == "" and P.fingerprint(None) == ""


def test_default_off_and_fingerprint_unchanged_when_off():
    p = SeedAdmitParams()
    assert p.group_flow_part_shape == ""
    assert "group_flow_part_shape" in p.model_dump()        # 路径参数，不进指纹；内容指纹只在开时另算


def test_pass_lifts_pending_fixes_admitted_and_skips_others():
    class R:
        def __init__(self, **k):
            self.__dict__.update(dict(id="b:1:1:1", slot=1, sub=None, evidence={}, doubts=["near_form"]), **k)

    class C:
        col = 1

        def __init__(self, chars):
            self.chars = chars
    import pytest
    hum = R(admit=True, char="刺", channel="human", provenance="human")
    pend = R(id="b:1:1:2", admit=False, char="刺", channel=None, provenance="match")
    other = R(id="b:1:1:3", admit=False, char="之", channel=None, provenance="match")
    adm = R(id="b:1:1:4", admit=True, char="刺", channel="group_flow", provenance="context", doubts=[])
    same = R(id="b:1:1:5", admit=True, char="剌", channel="match_ref", provenance="match", doubts=[])
    guard = R(id="b:1:1:6", admit=False, char="刺", channel=None, provenance="match", doubts=["护栏:never_match"])
    p2 = R(id="b:1:1:7", admit=False, char="踈", channel=None, provenance="match")
    abst = R(id="b:1:1:8", admit=False, char="踈", channel=None, provenance="match")
    p = SeedAdmitParams(patch_missing="skip")
    object.__setattr__(p, "group_flow_part_shape", "x")
    model = {"_chars": frozenset("剌刺疎踈"), "pairs": [{"chars": ["剌", "刺"]}, {"chars": ["疎", "踈"]}]}

    def judge(img, pair):
        if pair["chars"][0] == "剌":
            return {"char": "剌", "why": "agree", "p": 0.01, "pair": "剌刺"}
        return {"char": None, "why": "abstain:low_p", "p": 0.5, "pair": "疎踈"} if img.shape == (5, 5) else {"char": "疎", "why": "agree", "p": 0.0, "pair": "疎踈"}
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(P, "load", lambda path: model)
        mp.setattr(P, "judge", judge)
        mp.setattr(sa, "_page_patch", lambda ctx, page, col, slot, sub: np.zeros((5, 5) if slot == 8 else (4, 4), np.uint8))
        abst.slot = 8
        assert sa._part_shape_pass(p, [C([hum, pend, other, adm, same, guard, p2, abst])], {}) == 2
    finally:
        mp.undo()
    assert hum.char == "刺" and hum.channel == "human"
    assert pend.admit and pend.char == "剌" and pend.channel == "part_shape" and pend.evidence["lifted_from"]["char"] == "刺"
    assert not other.admit and "part_shape" not in other.evidence
    assert adm.char == "剌" and adm.channel == "part_shape" and adm.evidence["fixed_from"] == {"channel": "group_flow", "char": "刺"}
    assert same.channel == "match_ref" and "fixed_from" not in same.evidence
    assert not guard.admit and guard.char == "刺" and "part_shape" not in guard.evidence
    assert p2.admit and p2.char == "疎" and p2.channel == "part_shape"            # 第二对按本格字找对
    assert not abst.admit and abst.char == "踈" and abst.evidence["part_shape"]["why"] == "abstain:low_p"
