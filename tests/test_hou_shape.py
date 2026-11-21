"""候𠋫 书级刻形判法（`groups.hou_shape`、`seed_admit._hou_shape_pass`）。"""
from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.groups import hou_shape as H
from open_guji_cv.steps import seed_admit as sa
from open_guji_cv.steps.seed_admit import SeedAdmitParams


def _glyph(second: float) -> np.ndarray:
    """亻（左边一长竖）＋ 右边一条长 second×字高 的第二竖 ＋ 右半一块 矦 似的横撇。"""
    g = np.full((200, 200), 255, np.uint8)
    cv2.line(g, (40, 10), (10, 70), 0, 6)          # 亻 撇
    cv2.line(g, (30, 40), (30, 195), 0, 8)         # 亻 竖
    top = 195 - int(second * 185)
    cv2.line(g, (70, top), (70, 195), 0, 8)        # 第二竖
    for y in (40, 80, 120):
        cv2.line(g, (100, y), (190, y), 0, 6)
    cv2.line(g, (145, 120), (110, 190), 0, 6)
    cv2.line(g, (145, 120), (190, 190), 0, 6)
    return g


def _cfg(tmp_path, lo=0.52, hi=0.70):
    f = tmp_path / "hou_shape.json"
    f.write_text(json.dumps({"schema": H.SCHEMA, "chars": ["候", "𠋫"], "lo": lo, "hi": hi}), encoding="utf-8")
    return f


def test_second_vertical_orders_short_and_long():
    short, long_ = H.second_vertical(_glyph(0.25)), H.second_vertical(_glyph(0.95))
    assert short is not None and long_ is not None and short < 0.52 <= 0.70 <= long_
    assert H.second_vertical(np.full((50, 50), 255, np.uint8)) is None
    rgb = np.repeat(_glyph(0.95)[..., None], 3, axis=2)
    assert H.second_vertical(rgb) == long_


def test_judge_thresholds(tmp_path):
    m = H.load(str(_cfg(tmp_path)))
    assert H.judge(_glyph(0.25), m)["char"] == "候"
    assert H.judge(_glyph(0.95), m)["char"] == "𠋫"
    mid = H.judge(_glyph(0.95), {**m, "lo": 0.0, "hi": 2.0})
    assert mid["char"] is None and mid["why"] == "abstain:mid"
    assert H.fingerprint(str(_cfg(tmp_path))) and H.fingerprint(None) == ""


def test_bad_config(tmp_path):
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"schema": "nope", "lo": 0.5, "hi": 0.7}), encoding="utf-8")
    with pytest.raises(ValueError):
        H.load(str(f))


def test_default_off():
    assert SeedAdmitParams().group_flow_hou_shape == ""


def test_pass_only_admitted_nonhuman(monkeypatch):
    class R:
        def __init__(self, **k):
            self.__dict__.update(dict(id="b:1:1:1", slot=1, sub=None, evidence={}, doubts=[]), **k)

    class C:
        col = 1

        def __init__(self, chars):
            self.chars = chars
    hum = R(admit=True, char="𠋫", channel="human", provenance="human")
    pend = R(id="b:1:1:2", admit=False, char="𠋫", channel=None, provenance="match")
    adm = R(id="b:1:1:3", admit=True, char="𠋫", channel="match_ref", provenance="match")
    same = R(id="b:1:1:4", admit=True, char="候", channel="match_ref", provenance="match")
    other = R(id="b:1:1:5", admit=True, char="侯", channel="match_ref", provenance="match")
    p = SeedAdmitParams()
    object.__setattr__(p, "group_flow_hou_shape", "x")
    monkeypatch.setattr(H, "load", lambda path: {})
    monkeypatch.setattr(H, "judge", lambda img, m: {"char": "候", "why": "agree", "v": 0.3})
    monkeypatch.setattr(sa, "_page_patch", lambda *a, **k: np.zeros((4, 4), np.uint8))
    assert sa._hou_shape_pass(p, [C([hum, pend, adm, same, other])]) == 0
    assert hum.char == "𠋫" and "hou_shape" not in hum.evidence
    assert not pend.admit and pend.char == "𠋫" and "hou_shape" not in pend.evidence      # 待审不补放（可能是 侯）
    assert adm.char == "候" and adm.channel == "match_ref" and adm.evidence["fixed_from"] == {"channel": "match_ref", "char": "𠋫"}
    assert same.char == "候" and "fixed_from" not in same.evidence and same.evidence["hou_shape"]["char"] == "候"
    assert other.char == "侯" and "hou_shape" not in other.evidence


def test_codepoint_exempt_keeps_shape_hou():
    class B:
        def canonical_char(self, c):
            return {"候": "𠋫"}.get(c, c)

    class R:
        channel, provenance = "match_ref", "match"

        def __init__(self, char, ev):
            self.char, self.evidence = char, ev
    assert sa._codepoint_exempt(R("候", {"hou_shape": {"char": "候"}}), B())
    assert not sa._codepoint_exempt(R("候", {"hou_shape": {"char": None}}), B())
    assert not sa._codepoint_exempt(R("候", {}), B())


def test_net_schema_judges_by_prob(tmp_path):
    """hou_shape/2：小网的「候」概率过 t 给 候、低于 1−t 给 𠋫，其间弃权（权重造成恒值输出）。"""
    import base64
    import json

    import numpy as np

    from open_guji_cv.groups import hou_shape as H

    def arr(a):
        a = np.asarray(a, np.float32)
        return {"shape": list(a.shape), "dtype": "<f4", "b64": base64.b64encode(a.tobytes()).decode()}

    def net(bias):
        return {"f.0.weight": arr(np.zeros((16, 1, 3, 3))), "f.0.bias": arr(np.zeros(16)),
                "f.3.weight": arr(np.zeros((32, 16, 3, 3))), "f.3.bias": arr(np.zeros(32)),
                "f.6.weight": arr(np.zeros((64, 32, 3, 3))), "f.6.bias": arr(np.zeros(64)),
                "f.11.weight": arr(np.zeros((64, 64 * 8 * 8))), "f.11.bias": arr(np.zeros(64)),
                "f.13.weight": arr(np.zeros((1, 64))), "f.13.bias": arr([bias])}
    img = np.full((80, 80), 255, np.uint8)
    img[10:70, 15:20] = 0
    img[10:70, 40:45] = 0
    for bias, want in ((8.0, "候"), (-8.0, "𠋫"), (0.0, None)):
        p = tmp_path / f"h{bias}.json"
        p.write_text(json.dumps({"schema": "hou_shape/2", "chars": ["候", "𠋫"], "t": 0.98, "nets": [net(bias)]}), encoding="utf-8")
        r = H.judge(img, H.load(str(p)))
        assert r["char"] == want, (bias, r)
    assert H.judge(np.full((80, 80), 255, np.uint8), H.load(str(p)))["why"] == "abstain:no_ink"


def test_late_pass_only_unjudged(monkeypatch):
    """group_flow_hou_shape_late：5c 补放的格补判刻形，已判过的格不再动（全唐文 ve1 053:23:9:6）。"""
    class R:
        def __init__(self, **k):
            self.__dict__.update(dict(slot=1, sub=None, doubts=[], provenance="match"), **k)

    class C:
        col = 1

        def __init__(self, chars):
            self.chars = chars
    judged = R(id="b:1:1:1", admit=True, char="𠋫", channel="match_ref", evidence={"hou_shape": {"char": None, "why": "abstain:mid"}})
    late = R(id="b:1:1:2", admit=True, char="候", channel="vis_ruling", evidence={"vis_ruling": {"char": "候"}})
    p = SeedAdmitParams()
    object.__setattr__(p, "group_flow_hou_shape", "x")
    monkeypatch.setattr(H, "load", lambda path: {})
    monkeypatch.setattr(H, "judge", lambda img, m: {"char": "候", "why": "agree", "p": 0.999})
    monkeypatch.setattr(sa, "_page_patch", lambda *a, **k: np.zeros((4, 4), np.uint8))
    sa._hou_shape_pass(p, [C([judged, late])], only_unjudged=True)
    assert judged.char == "𠋫" and judged.evidence["hou_shape"]["char"] is None
    assert late.char == "候" and late.evidence["hou_shape"]["char"] == "候"


def test_late_flag_default_off_not_in_dump():
    p = SeedAdmitParams()
    assert p.group_flow_hou_shape_late is False
    assert "group_flow_hou_shape_late" not in p.model_dump()
    assert SeedAdmitParams(group_flow_hou_shape_late=True).model_dump()["group_flow_hou_shape_late"] is True
