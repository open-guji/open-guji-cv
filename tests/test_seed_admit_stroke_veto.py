# -*- coding: utf-8 -*-
"""Step7 `stroke_veto`（笔画反向护栏，全唐文形近字线 11-13）：已放行非人裁格，笔画判与放行字的类相反 → 降审。

判法本身（配准、量缺口）在 `strokes` 有单测；这里只测接线与规则：笔画判用假的 `judge` 顶替，
模型用 `build` 在造出来的特征上学（`features` 也顶替），不读真书数据。
"""
from __future__ import annotations

import json

import numpy as np

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_match, write_product
from open_guji_cv.core.step import STEPS
from open_guji_cv.groups import stroke_veto as sv
from open_guji_cv.steps import seed_admit as sa
from open_guji_cv.steps.seed_admit import SeedAdmitParams
from open_guji_cv.strokes.template import from_polylines

BOOK, PAGE, COL, SLOT = "tbook", 1, 1, 7
SKIP = {"patch_missing": "skip"}


def _tpl(ch):
    return from_polylines(ch, [("横", np.array([[0, 0], [0, 100.0]])), ("竖", np.array([[0, 50], [100, 50.0]])),
                               ("横", np.array([[100, 0], [100, 100.0]]))])


def _model(tmp_path, monkeypatch):
    """jys／qg 两组：特征一维，己 0、已巳 1；千 0、干 1。"""
    feats = {}

    def fake_features(gray, gm):
        return feats[int(gray[0, 0])], False
    monkeypatch.setattr(sv, "features", fake_features)
    rng = np.random.default_rng(0)
    samples = {"jys": [], "qg": []}
    for i, (g, ch, mu) in enumerate([("jys", "己", 0.0)] * 20 + [("jys", "已", 1.0)] * 10 + [("jys", "巳", 1.0)] * 10
                                    + [("qg", "千", 0.0)] * 20 + [("qg", "干", 1.0)] * 20):
        feats[i] = np.array([mu + rng.normal(0, 0.05)])
        samples[g].append((np.full((2, 2), i, np.uint8), ch))
    m = sv.build(samples, {"jys": _tpl("巳"), "qg": _tpl("干")}, t=3.0, max_z=6.0)
    f = tmp_path / "stroke_veto.json"
    f.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return f, feats


def test_build_and_judge(tmp_path, monkeypatch):
    f, feats = _model(tmp_path, monkeypatch)
    m = sv.load(str(f))
    assert set(m["groups"]) == {"jys", "qg"}
    assert set(m["groups"]["jys"]["_stats"].means) == {"己", "已巳"}
    assert sv.group_of(m, "巳")[0] == "jys" and sv.group_of(m, "干")[0] == "qg" and sv.group_of(m, "日") == (None, None)
    gm = m["groups"]["jys"]
    feats[900], feats[901], feats[902] = np.array([0.0]), np.array([1.0]), np.array([0.5])
    assert sv.judge(np.full((2, 2), 900, np.uint16), gm)["cls"] == "己"
    assert sv.judge(np.full((2, 2), 901, np.uint16), gm)["cls"] == "已巳"
    assert sv.judge(np.full((2, 2), 902, np.uint16), gm)["why"] == "out"          # 离两类都远（各 7 个标准差）：离群弃权
    st = gm["_stats"]
    mid = min(np.linspace(0, 1, 201), key=lambda v: abs(np.subtract(*st.loglik(np.array([v])).values())))
    feats[904] = np.array([mid])
    assert sv.judge(np.full((2, 2), 904, np.uint16), {**gm, "max_z": None})["why"] == "abstain"   # 不设 max_z：两类似然相当，弃权
    assert sv.fingerprint(str(f)) != "missing" and sv.fingerprint(str(tmp_path / "nope.json")) == "missing"


def _run(tmp_path, monkeypatch, *, cands, judged, params=None, keep_load=False):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, verdict="unsure", cov=cands[0][1], wmax=4.0, char=None,
                                        candidates=cands)]))
    monkeypatch.setattr(sa, "_page_patch", lambda *a, **k: np.zeros((4, 4), np.uint8))
    # 接线测试用不进字组流程的字对（陪／培走 match_solo 放行），免得字组流程先把格留审
    if not keep_load:
        monkeypatch.setattr(sv, "load", lambda path: {"groups": {"jys": {"classes": {"陪": "陪", "培": "培"}}}})
    monkeypatch.setattr(sv, "judge", lambda img, gm: judged)
    ctx.params["seed_admit"] = SeedAdmitParams(**{"shadow_veto": False, **SKIP, **(params or {})})
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    (r,) = col.chars
    return r


C1 = [("陪", 0.9930), ("培", 0.9100)]
ON = {"stroke_veto": "/nonexistent/stroke_veto.json"}


def test_default_off(tmp_path, monkeypatch):
    assert SeedAdmitParams().stroke_veto == ""
    r = _run(tmp_path, monkeypatch, cands=C1, judged={"cls": "培", "why": "llr"})
    assert r.admit and r.char == "陪"


def test_contradict_demotes(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=C1, judged={"cls": "培", "why": "llr", "llr": 7.0, "x": [1.0]}, params=ON)
    assert not r.admit and "stroke_veto" in r.doubts, (r.channel, r.doubts)
    assert r.evidence["stroke_veto"]["cls"] == "培"
    assert r.evidence["demoted_from"]["by"] == "stroke_veto"


def test_agree_or_abstain_keeps(tmp_path, monkeypatch):
    for judged in ({"cls": "陪", "why": "llr"}, {"cls": None, "why": "abstain"}, {"cls": None, "why": "bad_fit"}):
        r = _run(tmp_path, monkeypatch, cands=C1, judged=judged, params=ON)
        assert r.admit and r.char == "陪" and "stroke_veto" not in (r.doubts or []), judged


def test_channels_filter(tmp_path, monkeypatch):
    ctx_model = {"groups": {"jys": {"classes": {"陪": "陪", "培": "培"}, "channels": ["group_flow"]}}}
    monkeypatch.setattr(sv, "load", lambda path: ctx_model)
    r = _run(tmp_path, monkeypatch, cands=C1, judged={"cls": "培", "why": "llr"}, params=ON, keep_load=True)
    assert r.admit and r.channel == "match_solo"          # 不在 channels 里的通道不看


def test_char_outside_groups_untouched(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=[("冢", 0.9941), ("冡", 0.9)], judged={"cls": "培", "why": "llr"}, params=ON)
    assert r.admit and r.char == "冢"


def test_pass_skips_human():
    class R:
        def __init__(self, **k):
            self.__dict__.update(dict(id="b:1:1:1", slot=1, sub=None, evidence={}, doubts=[]), **k)

    class C:
        col = 1

        def __init__(self, chars):
            self.chars = chars
    hum = R(admit=True, char="己", channel="human", provenance="human")
    p = SeedAdmitParams(**SKIP)
    object.__setattr__(p, "stroke_veto", "x")
    import pytest
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(sv, "load", lambda path: {"groups": {"jys": {"classes": {"己": "己", "已": "已巳"}}}})
        mp.setattr(sv, "judge", lambda img, gm: {"cls": "已巳", "why": "llr"})
        mp.setattr(sa, "_page_patch", lambda *a, **k: np.zeros((4, 4), np.uint8))
        assert sa._stroke_veto_pass(p, [C([hum])]) == 0 and hum.admit
    finally:
        mp.undo()


def test_params_not_in_dump_when_off(tmp_path):
    d = SeedAdmitParams().model_dump()
    assert "stroke_veto" not in d and "stroke_veto_fingerprint" not in d
    f = tmp_path / "m.json"
    f.write_text("{}", encoding="utf-8")
    d = SeedAdmitParams(stroke_veto=str(f)).model_dump()
    assert d["stroke_veto"] == str(f) and d["stroke_veto_fingerprint"] == sv.fingerprint(str(f))


def test_ruling_first_not_in_dump_when_off():
    d = SeedAdmitParams().model_dump()
    assert "group_flow_ruling_first" not in d
    assert SeedAdmitParams(group_flow_ruling_first=["jys"]).model_dump()["group_flow_ruling_first"] == ["jys"]
