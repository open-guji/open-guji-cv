"""3b `glyph_near` 的 wu_shape 方法（嗚鳴 书级刻形判法从第四步搬来，照 rr_shape 样板，2026-11-28）。

数据全在测试里造（字块图、模型权重同 `test_wu_shape.py`）。一致性：同一张图、同一个模型，走第四步
`seed_admit_shapes._wu_shape_pass` 与走 3b 方法，证据逐键相同。
"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import cv2
import numpy as np
import pytest

from open_guji_cv.groups import near_methods as NM
from open_guji_cv.groups import wu_shape

from helpers import make_book, make_ctx, page_chars, page_match, run_steps, write_product
from test_wu_shape import _glyph, _model_file


def _blank():
    return np.full((120, 120), 255, np.uint8)


def _glyph2():
    """口旁＋不带中横的方框（烏 那样），挪一点位。"""
    g = np.full((110, 130), 255, np.uint8)
    cv2.rectangle(g, (10, 45), (32, 75), 0, 4)
    cv2.rectangle(g, (55, 12), (112, 72), 0, 5)
    cv2.line(g, (50, 95), (118, 95), 0, 5)
    return g


def _imgs():
    return [_glyph(), _glyph2(), _blank()]


@pytest.fixture
def models(tmp_path):
    """判 鳴（偏置 +8）、判 嗚（−8）、p＝0.5 弃权（全零）、随机权重（p 在中间）四份模型。"""
    d = tmp_path / "groups"
    d.mkdir()
    return {k: _model_file(d, **kw, name=f"{k}.json")[0]
            for k, kw in (("ming", {"bias": 8.0}), ("wu", {"bias": -8.0}), ("mid", {"zero": True}), ("rand", {}))}


# ── 方法：形状 ─────────────────────────────────────────────────────────

def test_score_shapes_and_no_calib(models):
    for k, want in (("ming", "鳴"), ("wu", "嗚"), ("mid", None)):
        m = NM.load_method("wu_shape", str(models[k]))
        assert m.patch == "char_patch"
        o, o2, blank = m.score(_imgs(), "anybook")
        assert o["evidence"]["method"] == "wu_shape" and o["evidence"]["char"] == want
        assert set(o["sims"]) == {"嗚", "鳴"} and o["sims"]["鳴"] == o["evidence"]["p"]
        assert o["sims"]["嗚"] + o["sims"]["鳴"] == pytest.approx(1.0, abs=1e-9)
        if want:
            assert max(o["sims"], key=o["sims"].get) == want
        else:
            assert o["evidence"]["why"] == "abstain:low_p"                 # 门槛中间仍给分，弃权记在证据里
        assert blank == {"sims": {}, "evidence": {"method": "wu_shape", "char": None, "why": "abstain:no_ink"}}
        assert all(m.calibrate(x["sims"]) is None for x in (o, o2, blank))   # 没有校准表：收尾不出 p


def test_calibrate_with_sibling_calib(models):
    f = models["rand"]
    (f.parent / "rand.calib.json").write_text(json.dumps(
        {"format": "near-calib/1", "knots": {"鳴": [[0.0, 1.0], [0.1, 0.9]]}}), encoding="utf-8")
    m = NM.WuShape(f)
    o = m.score([_glyph()], "b")[0]
    p = m.calibrate(o["sims"])
    assert p["鳴"] == pytest.approx(0.1 + 0.8 * o["sims"]["鳴"], abs=1e-4) and p["鳴"] + p["嗚"] == pytest.approx(1.0)
    assert m.calibrate({}) is None
    fp0 = NM.method_fingerprint("wu_shape", str(f))                         # 校准表进方法指纹：换表即换指纹
    (f.parent / "rand.calib.json").write_text(json.dumps({"format": "near-calib/1", "knots": {}}), encoding="utf-8")
    assert NM.method_fingerprint("wu_shape", str(f)) != fp0
    (f.parent / "rand.calib.json").write_text(json.dumps({"format": "x"}), encoding="utf-8")
    with pytest.raises(ValueError):
        NM.WuShape(f)


def test_model_dir_form(tmp_path):
    d = tmp_path / "wu_dir"
    d.mkdir()
    _model_file(d, bias=8.0, name="model.json")
    m = NM.load_method("wu_shape", str(d))
    assert m.score([_glyph()], "b")[0]["evidence"]["char"] == "鳴"
    assert m.fingerprint() == NM._dir_fingerprint(d)
    assert m.model_sha == wu_shape.fingerprint(str(d / "model.json"))


# ── 一致性：第四步现役判法 vs 3b 方法 ──────────────────────────────────

@pytest.mark.parametrize("k", ["ming", "wu", "mid", "rand"])
@pytest.mark.parametrize("admitted", [False, True])
def test_same_input_same_evidence_as_seed_admit_pass(models, k, admitted):
    """同一张图、同一个模型：第四步 `_wu_shape_pass` 写进格的 `evidence.wu_shape` 与 3b 方法的证据（去掉 method）逐键相同。"""
    from open_guji_cv.steps.seed_admit_shapes import _wu_shape_pass

    imgs = _imgs()
    keys = [f"p0001c01s{i + 1}" for i in range(len(imgs))]
    ctx = NS(image=lambda kind, key: imgs[keys.index(key)])
    recs = [NS(id=f"b:1:1:{i + 1}", slot=i + 1, sub=None, char="鳴", admit=admitted, evidence={},
               provenance="match", channel="match_ref" if admitted else "", doubts=[]) for i in range(len(imgs))]
    p = NS(group_flow_wu_shape=str(models[k]), patch_missing="error")
    _wu_shape_pass(p, [NS(col=1, chars=recs)], {}, ctx, 1)
    outs = NM.load_method("wu_shape", str(models[k])).score(imgs, "b")
    model = wu_shape.load(str(models[k]))
    for r, o, g in zip(recs, outs, imgs):
        mine = {kk: v for kk, v in o["evidence"].items() if kk != "method"}
        assert mine == wu_shape.judge(g, model)
        if "wu_shape" in r.evidence:                                  # 现役记了（待审格全记；已放行格只在改字时记）
            assert r.evidence["wu_shape"] == mine
        else:
            assert admitted and mine["char"] in (None, "鳴")
        if mine["char"] is not None:                                  # 现役定了字：3b 给同一个字最高分
            assert r.char == mine["char"] == max(o["sims"], key=o["sims"].get)
            assert r.admit
        else:
            assert r.admit == admitted and r.char == "鳴"


# ── 端到端 ─────────────────────────────────────────────────────────────

def _glyph_near_step():
    from open_guji_cv.core.step import STEPS
    return STEPS["glyph_near"]


def test_glyph_near_wu_shape_end_to_end(tmp_path, models):
    from open_guji_cv.steps.glyph_near import GlyphNearParams

    mf = models["ming"]
    groups = {"wu": {"ref": "wu", "trigger": "cands", "methods": {"wu_shape": str(mf)}}}
    book = make_book("tbook", params={"glyph_near": {"groups": groups}, "glyph_analyzer": {"enabled": True}})
    ctx = make_ctx(tmp_path, book, raw={1: np.full((400, 300), 255, np.uint8)})
    imgs = {1: _glyph(), 2: _glyph2(), 3: _glyph(), 6: _blank()}
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(recs=[
        {"slot": 1, "verdict": "unsure", "candidates": [("嗚", 0.90), ("鳴", 0.89)]},
        {"slot": 2, "verdict": "same", "char": "鳴", "cov": 0.95},
        {"slot": 3, "verdict": "unsure", "candidates": [("鴨", 0.90), ("鵝", 0.8), ("鳴", 0.7)]},   # 首位不在组里：3b 也跑，4d 不读
        {"slot": 4, "verdict": "unsure", "candidates": [("嗚", 0.90)]},             # 字块图读不到
        {"slot": 5, "verdict": "same", "char": "言", "cov": 0.95},                  # 不触发
        {"slot": 6, "verdict": "unsure", "candidates": [("鳴", 0.90)]}]))           # 空白：弃权、无分
    write_product(ctx, "cell_shrink", 1, char_index=page_chars(recs=[
        {"slot": s, "bbox_page": (30.0, 10.0 + 50 * s, 70.0, 50.0 + 50 * s), "patch_key": f"p0001c01s{s}"}
        for s in range(1, 7)]))
    for s, g in imgs.items():
        ctx.cache.put("tbook", "char_patch", f"p0001c01s{s}", g)

    p = ctx.params_for(_glyph_near_step())
    assert p.groups["wu"]["chars"] == ["嗚", "鳴"] and "ref" not in p.groups["wu"]    # 按登记表展开
    assert p.methods_sha == "wu:" + NM.method_fingerprint("wu_shape", str(mf))
    assert p.methods_sha == GlyphNearParams(groups=p.groups).methods_sha

    out = run_steps(ctx, 1, ["glyph_near", "glyph_analyzer"])
    pn = out["glyph_near"]
    sha = wu_shape.fingerprint(str(mf))                                     # 与第四步参数指纹 ws 段同算法
    assert pn.models == {"wu_shape:wu": sha}
    # 4d 读口比 methods_sha 里的 `wu_shape=<指纹>`，与它按 group_flow_wu_shape 算的同一份
    assert NM.method_fingerprint("wu_shape", str(mf)) in {x.split(":", 1)[1] for x in pn.methods_sha.split(";")}
    near = pn.by_id()
    assert list(near) == [f"tbook:1:1:{s}" for s in (1, 2, 3, 4, 6)]
    model = wu_shape.load(str(mf))
    trail = {}
    for s in (1, 2, 3, 6):
        mo = near[f"tbook:1:1:{s}"].methods[0]
        assert mo.method == "wu_shape:wu" and near[f"tbook:1:1:{s}"].trigger == "cands"
        trail[s] = {"method": "wu_shape", **wu_shape.judge(imgs[s], model)}
        assert mo.evidence == trail[s]
    assert [trail[s]["char"] for s in (1, 2, 3, 6)] == ["鳴", "鳴", "鳴", None]
    assert trail[6]["why"] == "abstain:no_ink" and near["tbook:1:1:6"].methods[0].sims == {}
    miss = near["tbook:1:1:4"].methods[0]
    assert miss.sims == {} and miss.evidence["error"] == "patch_missing"

    fin = out["glyph_analyzer"].by_id()
    a = fin["tbook:1:1:1"]
    assert a.p_src == "" and all(c.p is None for c in a.cands)              # 没有校准表：只当证据
    assert {c.char: c.evidence["b"]["wu_shape:wu"] for c in a.cands if "b" in c.evidence} == {
        "鳴": trail[1]["p"], "嗚": round(1 - trail[1]["p"], 4)}
    for s in (1, 2, 3, 6):                                                  # 4d 取数处：每格 near.methods[方法名]
        assert fin[f"tbook:1:1:{s}"].near == {"group": "wu", "trigger": "cands",
                                              "methods": {"wu_shape": {**trail[s], "model": sha}}}
    assert fin["tbook:1:1:4"].near["methods"]["wu_shape"]["error"] == "patch_missing"
    assert fin["tbook:1:1:5"].near == {} and "near" not in fin["tbook:1:1:5"].model_dump(mode="json")
