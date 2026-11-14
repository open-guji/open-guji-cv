"""嗚鳴 书级刻形判法（`groups.wu_shape`，全唐文 11-14）：numpy 前向对得上逐点算法、门槛与弃权、seed_admit 接线。
数据与权重全在测试里造，不读真书数据。"""
from __future__ import annotations

import base64
import json

import cv2
import numpy as np

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.groups import wu_shape as W
from open_guji_cv.steps import seed_admit as sa
from open_guji_cv.steps.seed_admit import SeedAdmitParams

SHAPES = {"f.0.weight": (16, 1, 3, 3), "f.0.bias": (16,), "f.3.weight": (32, 16, 3, 3), "f.3.bias": (32,),
          "f.6.weight": (64, 32, 3, 3), "f.6.bias": (64,), "f.11.weight": (64, 4096), "f.11.bias": (64,),
          "f.13.weight": (1, 64), "f.13.bias": (1,)}


def _enc(a):
    return {"shape": list(a.shape), "dtype": "<f4", "b64": base64.b64encode(np.ascontiguousarray(a, "<f4").tobytes()).decode()}


def _model_file(tmp_path, bias=0.0, zero=False, name="wu_shape.json"):
    rng = np.random.default_rng(0)
    net = {k: (np.zeros(s, np.float32) if zero else rng.normal(0, 0.05, s).astype(np.float32)) for k, s in SHAPES.items()}
    net["f.13.bias"] = np.array([bias], np.float32)
    if bias:
        net["f.13.weight"] = np.zeros((1, 64), np.float32)
    f = tmp_path / name
    f.write_text(json.dumps({"schema": W.SCHEMA, "chars": ["嗚", "鳴"], "size": 64, "top": 0.75, "t": 0.99,
                             "nets": [{k: _enc(v) for k, v in net.items()}]}), encoding="utf-8")
    return f, net


def _glyph():
    """口旁（左）＋右边一个带横的方框。"""
    g = np.full((120, 120), 255, np.uint8)
    cv2.rectangle(g, (8, 40), (30, 70), 0, 4)
    cv2.rectangle(g, (50, 10), (105, 70), 0, 5)
    cv2.line(g, (50, 35), (105, 35), 0, 5)
    cv2.line(g, (45, 90), (110, 90), 0, 5)
    return g


def _naive(net, x):
    def conv(h, w, b):
        C, H, Wd = h.shape
        hp = np.pad(h, ((0, 0), (1, 1), (1, 1)))
        out = np.zeros((w.shape[0], H, Wd), np.float64)
        for o in range(w.shape[0]):
            for i in range(H):
                for j in range(Wd):
                    out[o, i, j] = (hp[:, i:i + 3, j:j + 3] * w[o]).sum() + b[o]
        return out

    def pool(h):
        return h.reshape(h.shape[0], h.shape[1] // 2, 2, h.shape[2] // 2, 2).max((2, 4))
    h = x[None].astype(np.float64)
    for k in ("f.0", "f.3", "f.6"):
        h = pool(np.maximum(conv(h, net[k + ".weight"], net[k + ".bias"]), 0))
    h = np.maximum(net["f.11.weight"] @ h.reshape(-1) + net["f.11.bias"], 0)
    z = float((net["f.13.weight"] @ h + net["f.13.bias"])[0])
    return 1 / (1 + np.exp(-z))


def test_forward_matches_naive(tmp_path):
    f, net = _model_file(tmp_path)
    m = W.load(str(f))
    g = _glyph()
    x = W.prep(g)
    assert x is not None and x.shape == (64, 64)
    assert abs(W.prob(g, m) - _naive(net, x)) < 1e-5


def test_threshold_and_abstain(tmp_path):
    g = _glyph()
    hi = W.load(str(_model_file(tmp_path, bias=8.0, name="a.json")[0]))
    lo = W.load(str(_model_file(tmp_path, bias=-8.0, name="b.json")[0]))
    mid = W.load(str(_model_file(tmp_path, zero=True, name="c.json")[0]))
    assert W.judge(g, hi)["char"] == "鳴" and W.judge(g, lo)["char"] == "嗚"
    v = W.judge(g, mid)
    assert v["char"] is None and v["why"] == "abstain:low_p" and v["p"] == 0.5
    assert W.judge(np.full((80, 80), 255, np.uint8), hi) == {"char": None, "why": "abstain:no_ink"}
    assert W.fingerprint(str(tmp_path / "a.json")) and W.fingerprint(str(tmp_path / "nope.json")) == ""


SKIP = {"patch_missing": "skip"}


def test_default_off_and_hidden():
    assert SeedAdmitParams().group_flow_wu_shape == ""
    assert "group_flow_wu_shape" in SeedAdmitParams().model_dump()     # 路径参数（path_params），不进指纹；内容指纹另算


def test_pass_skips_human_and_lifts_pending():
    class R:
        def __init__(self, **k):
            self.__dict__.update(dict(id="b:1:1:1", slot=1, sub=None, evidence={}, doubts=["near_form"]), **k)

    class C:
        col = 1

        def __init__(self, chars):
            self.chars = chars
    import pytest
    hum = R(admit=True, char="鳴", channel="human", provenance="human")
    pend = R(id="b:1:1:2", admit=False, char="鳴", channel=None, provenance="match")
    other = R(id="b:1:1:3", admit=False, char="之", channel=None, provenance="match")
    adm = R(id="b:1:1:4", admit=True, char="鳴", channel="group_flow", provenance="context", doubts=[])
    same = R(id="b:1:1:5", admit=True, char="嗚", channel="match_ref", provenance="match", doubts=[])
    p = SeedAdmitParams(**SKIP)
    object.__setattr__(p, "group_flow_wu_shape", "x")
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(W, "load", lambda path: {})
        mp.setattr(W, "judge", lambda img, m: {"char": "嗚", "why": "agree", "p": 0.001})
        mp.setattr(sa, "_page_patch", lambda *a, **k: np.zeros((4, 4), np.uint8))
        assert sa._wu_shape_pass(p, [C([hum, pend, other, adm, same])], {}) == 1
    finally:
        mp.undo()
    assert hum.char == "鳴" and hum.channel == "human"
    assert pend.admit and pend.char == "嗚" and pend.channel == "wu_shape" and pend.evidence["lifted_from"]["char"] == "鳴"
    assert not other.admit and "wu_shape" not in other.evidence
    assert adm.admit and adm.char == "嗚" and adm.channel == "wu_shape" and adm.evidence["fixed_from"] == {"channel": "group_flow", "char": "鳴"}
    assert same.char == "嗚" and same.channel == "match_ref" and "fixed_from" not in same.evidence
