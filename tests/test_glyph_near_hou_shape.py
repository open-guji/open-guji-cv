"""3b `glyph_near` 的 hou_shape 方法（候𠋫 书级刻形判法从第四步搬来，照 rr_shape 样板，2026-11-28）。

数据全在测试里造（字块图同 `test_hou_shape.py`，/1 几何阈值、/2 小网权重都现造）。一致性：同一张图、同一个模型，走第四步
`seed_admit_shapes._hou_shape_pass`（主遍、晚跑遍）与走 3b 方法，证据逐键相同；/1 的几何量映射与现役判定一致。
"""
from __future__ import annotations

import base64
import json
from types import SimpleNamespace as NS

import numpy as np
import pytest

from open_guji_cv.groups import hou_shape
from open_guji_cv.groups import near_methods as NM

from helpers import make_book, make_ctx, page_chars, page_match, run_steps, write_product
from test_hou_shape import _glyph


def _blank():
    return np.full((200, 200), 255, np.uint8)


def _imgs():
    """短第二竖（候）、中间档、长第二竖（𠋫）、空白（无墨）。"""
    return [_glyph(0.25), _glyph(0.6), _glyph(0.95), _blank()]


def _arr(a):
    a = np.asarray(a, np.float32)
    return {"shape": list(a.shape), "dtype": "<f4", "b64": base64.b64encode(a.tobytes()).decode()}


def _net(bias, rng=None):
    def w(*s):
        return _arr(rng.normal(0, 0.05, s) if rng is not None else np.zeros(s))
    return {"f.0.weight": w(16, 1, 3, 3), "f.0.bias": w(16), "f.3.weight": w(32, 16, 3, 3), "f.3.bias": w(32),
            "f.6.weight": w(64, 32, 3, 3), "f.6.bias": w(64), "f.11.weight": w(64, 64 * 8 * 8), "f.11.bias": w(64),
            "f.13.weight": w(1, 64), "f.13.bias": _arr([bias])}


@pytest.fixture
def models(tmp_path):
    """/1 几何阈值（书里那组 lo／hi）＋ /2 小网：判 候（+8）、判 𠋫（−8）、p＝0.5 弃权（全零）、随机权重。"""
    d = tmp_path / "groups"
    d.mkdir()
    out = {}
    f = d / "geo.json"
    f.write_text(json.dumps({"schema": hou_shape.SCHEMA, "chars": ["候", "𠋫"], "lo": 0.52, "hi": 0.70}), encoding="utf-8")
    out["geo"] = f
    for k, nets in (("hou", [_net(8.0)]), ("alt", [_net(-8.0)]), ("mid", [_net(0.0)]),
                    ("rand", [_net(0.0, np.random.default_rng(0)), _net(0.0, np.random.default_rng(1))])):
        f = d / f"{k}.json"
        f.write_text(json.dumps({"schema": hou_shape.SCHEMA_NET, "chars": ["候", "𠋫"], "t": 0.98, "nets": nets}),
                     encoding="utf-8")
        out[k] = f
    return out


# ── 方法：形状、/1 映射 ────────────────────────────────────────────────

def test_geo_schema_sims_follow_judge(models):
    m = NM.load_method("hou_shape", str(models["geo"]))
    assert m.patch == "char_patch"
    short, mid, long_, blank = m.score(_imgs(), "anybook")
    assert short["evidence"]["char"] == "候" and long_["evidence"]["char"] == "𠋫"
    assert mid["evidence"] == {"method": "hou_shape", "char": None, "why": "abstain:mid", "v": mid["evidence"]["v"]}
    assert short["sims"]["候"] >= 0.9 and long_["sims"]["候"] <= 0.1 and 0.1 < mid["sims"]["候"] < 0.9
    for o in (short, mid, long_):
        assert set(o["sims"]) == {"候", "𠋫"} and o["sims"]["候"] + o["sims"]["𠋫"] == pytest.approx(1.0, abs=1e-9)
    assert blank == {"sims": {}, "evidence": {"method": "hou_shape", "char": None, "why": "abstain:no_ink"}}
    assert all(m.calibrate(o["sims"]) is None for o in (short, mid, long_, blank))      # 没有校准表：收尾不出 p


def test_geo_mapping_monotone_and_consistent_at_edges(models):
    """/1：v 越长 候 分越低；判 候 的 v（< lo，含取 4 位后等于 lo 的）候 ≥ 0.9，判 𠋫 的（≥ hi）候 ≤ 0.1；lo＝hi 按判出的字给分。"""
    m = NM.load_method("hou_shape", str(models["geo"]))
    vs = [0.0, 0.3, 0.5199, 0.52, 0.55, 0.61, 0.65, 0.6999, 0.70, 0.9, 1.0]
    qs = [m.sims_of({"char": None, "why": "x", "v": v})["候"] for v in vs]
    assert qs == sorted(qs, reverse=True) and len(set(qs)) == len(qs)
    assert m.sims_of({"v": 0.52})["候"] == 0.9 and m.sims_of({"v": 0.61})["候"] == 0.5 and m.sims_of({"v": 0.70})["候"] == 0.1
    for s in np.linspace(0.05, 1.0, 40):                              # 现役判定与 sims 最高分一致（扫第二竖长）
        v = hou_shape.judge(_glyph(float(s)), m.model)
        sims = m.sims_of(v)
        if v["char"] is not None:
            assert max(sims, key=sims.get) == v["char"] and max(sims.values()) >= 0.9
        else:
            assert 0.1 < sims["候"] < 0.9
    m = NM.HouShape(models["geo"])                                     # 另起一个对象改阈值，不动 load_method 的缓存
    m.model = {**m.model, "lo": 0.6, "hi": 0.6011}                     # 窄中间档：截断不溢出，仍保序
    assert m.sims_of({"v": 0.0}) == {"候": 1.0, "𠋫": 0.0} and m.sims_of({"v": 1.0}) == {"候": 0.0, "𠋫": 1.0}
    m.model = {**m.model, "lo": 0.6, "hi": 0.6}
    assert m.sims_of({"char": "候", "v": 0.6}) == {"候": 1.0, "𠋫": 0.0}
    assert m.sims_of({"char": "𠋫", "v": 0.6}) == {"候": 0.0, "𠋫": 1.0}


def test_net_schema_sims_are_prob(models):
    for k, want in (("hou", "候"), ("alt", "𠋫"), ("mid", None)):
        m = NM.load_method("hou_shape", str(models[k]))
        o = m.score([_glyph(0.6)], "b")[0]
        assert o["evidence"]["char"] == want and o["sims"] == {"候": o["evidence"]["p"], "𠋫": round(1 - o["evidence"]["p"], 4)}
        if want:
            assert max(o["sims"], key=o["sims"].get) == want
        else:
            assert o["evidence"]["why"] == "abstain:mid"


def test_calibrate_with_sibling_calib(models):
    f = models["geo"]
    (f.parent / "geo.calib.json").write_text(json.dumps(
        {"format": "near-calib/1", "knots": {"候": [[0.0, 1.0], [0.2, 0.8]]}}), encoding="utf-8")
    m = NM.HouShape(f)
    o = m.score([_glyph(0.25)], "b")[0]
    p = m.calibrate(o["sims"])
    assert p["候"] == pytest.approx(0.2 + 0.6 * o["sims"]["候"], abs=1e-4) and p["候"] + p["𠋫"] == pytest.approx(1.0)
    assert m.calibrate({}) is None
    fp0 = NM.method_fingerprint("hou_shape", str(f))
    (f.parent / "geo.calib.json").write_text(json.dumps({"format": "near-calib/1", "knots": {}}), encoding="utf-8")
    assert NM.method_fingerprint("hou_shape", str(f)) != fp0


def test_model_dir_form(tmp_path, models):
    d = tmp_path / "hou_dir"
    d.mkdir()
    (d / "model.json").write_bytes(models["geo"].read_bytes())
    m = NM.load_method("hou_shape", str(d))
    assert m.score([_glyph(0.95)], "b")[0]["evidence"]["char"] == "𠋫"
    assert m.fingerprint() == NM._dir_fingerprint(d) and m.model_sha == hou_shape.fingerprint(str(d / "model.json"))


# ── 一致性：第四步现役判法（主遍、晚跑遍）vs 3b 方法 ───────────────────

@pytest.mark.parametrize("k", ["geo", "hou", "alt", "mid", "rand"])
@pytest.mark.parametrize("late", [False, True])
def test_same_input_same_evidence_as_seed_admit_pass(models, k, late):
    """同一张图、同一个模型：`_hou_shape_pass` 给已放行 候𠋫 格写的 `evidence.hou_shape` 与 3b 证据（去 method）逐键相同，
    改出来的字＝3b 判的字＝sims 最高分；待审格现役不碰。晚跑遍（only_unjudged）判法同一个，已判过的格不再动。"""
    from open_guji_cv.steps.seed_admit_shapes import _hou_shape_pass

    imgs = _imgs()
    keys = [f"p0001c01s{i + 1}" for i in range(len(imgs))]
    ctx = NS(image=lambda kind, key: imgs[keys.index(key)])
    adm = [NS(id=f"b:1:1:{i + 1}", slot=i + 1, sub=None, char="𠋫", admit=True, evidence={}, provenance="match",
              channel="vis_ruling" if late else "match_ref", doubts=[]) for i in range(len(imgs))]
    pend = NS(id="b:1:2:1", slot=1, sub=None, char="𠋫", admit=False, evidence={}, provenance="match", channel="", doubts=[])
    done = NS(id="b:1:2:2", slot=2, sub=None, char="𠋫", admit=True, provenance="match", channel="match_ref", doubts=[],
              evidence={"hou_shape": {"char": None, "why": "abstain:mid", "v": 0.6}})
    p = NS(group_flow_hou_shape=str(models[k]), patch_missing="error")
    _hou_shape_pass(p, [NS(col=1, chars=adm), NS(col=2, chars=[pend] + ([done] if late else []))], ctx, 1,
                    only_unjudged=late)
    outs = NM.load_method("hou_shape", str(models[k])).score(imgs, "b")
    model = hou_shape.load(str(models[k]))
    for r, o, g in zip(adm, outs, imgs):
        mine = {kk: v for kk, v in o["evidence"].items() if kk != "method"}
        assert mine == hou_shape.judge(g, model) == r.evidence["hou_shape"]
        assert r.admit                                                    # 只改字、不改放行
        if mine["char"] is not None:
            assert r.char == mine["char"] == max(o["sims"], key=o["sims"].get)
        else:
            assert r.char == "𠋫" and "fixed_from" not in r.evidence
    assert pend.evidence == {} and not pend.admit
    assert done.evidence["hou_shape"] == {"char": None, "why": "abstain:mid", "v": 0.6}


# ── 端到端 ─────────────────────────────────────────────────────────────

def _glyph_near_step():
    from open_guji_cv.core.step import STEPS
    return STEPS["glyph_near"]


def test_glyph_near_hou_shape_end_to_end(tmp_path, models):
    from open_guji_cv.steps.glyph_near import GlyphNearParams

    mf = models["geo"]
    groups = {"hou": {"ref": "hou", "trigger": "cands", "methods": {"hou_shape": str(mf)}}}
    book = make_book("tbook", params={"glyph_near": {"groups": groups}, "glyph_analyzer": {"enabled": True}})
    ctx = make_ctx(tmp_path, book, raw={1: np.full((400, 300), 255, np.uint8)})
    imgs = {1: _glyph(0.25), 2: _glyph(0.95), 3: _glyph(0.6), 6: _blank()}
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(recs=[
        {"slot": 1, "verdict": "unsure", "candidates": [("𠋫", 0.90), ("侯", 0.89)]},
        {"slot": 2, "verdict": "same", "char": "𠋫", "cov": 0.95},
        {"slot": 3, "verdict": "unsure", "candidates": [("言", 0.90), ("文", 0.8), ("候", 0.7)]},   # 首位不在组里：3b 也跑
        {"slot": 4, "verdict": "unsure", "candidates": [("候", 0.90)]},             # 字块图读不到
        {"slot": 5, "verdict": "same", "char": "言", "cov": 0.95},                  # 不触发
        {"slot": 6, "verdict": "unsure", "candidates": [("𠋫", 0.90)]}]))           # 空白：弃权、无分
    write_product(ctx, "cell_shrink", 1, char_index=page_chars(recs=[
        {"slot": s, "bbox_page": (30.0, 10.0 + 50 * s, 70.0, 50.0 + 50 * s), "patch_key": f"p0001c01s{s}"}
        for s in range(1, 7)]))
    for s, g in imgs.items():
        ctx.cache.put("tbook", "char_patch", f"p0001c01s{s}", g)

    p = ctx.params_for(_glyph_near_step())
    assert p.groups["hou"]["chars"] == ["侯", "俟", "候", "𠉀", "𠋫"] and "ref" not in p.groups["hou"]   # 按登记表展开
    assert p.methods_sha == "hou:" + NM.method_fingerprint("hou_shape", str(mf))
    assert p.methods_sha == GlyphNearParams(groups=p.groups).methods_sha

    out = run_steps(ctx, 1, ["glyph_near", "glyph_analyzer"])
    pn = out["glyph_near"]
    sha = hou_shape.fingerprint(str(mf))                                    # 与第四步参数指纹 hs 段同算法
    assert pn.models == {"hou_shape:hou": sha}
    assert NM.method_fingerprint("hou_shape", str(mf)) in {x.split(":", 1)[1] for x in pn.methods_sha.split(";")}
    near = pn.by_id()
    assert list(near) == [f"tbook:1:1:{s}" for s in (1, 2, 3, 4, 6)]
    model = hou_shape.load(str(mf))
    trail = {}
    for s in (1, 2, 3, 6):
        mo = near[f"tbook:1:1:{s}"].methods[0]
        assert mo.method == "hou_shape:hou" and near[f"tbook:1:1:{s}"].trigger == "cands"
        trail[s] = {"method": "hou_shape", **hou_shape.judge(imgs[s], model)}
        assert mo.evidence == trail[s]
    assert [trail[s]["char"] for s in (1, 2, 3, 6)] == ["候", "𠋫", None, None]
    assert near["tbook:1:1:6"].methods[0].sims == {}
    miss = near["tbook:1:1:4"].methods[0]
    assert miss.sims == {} and miss.evidence["error"] == "patch_missing"

    fin = out["glyph_analyzer"].by_id()
    a = fin["tbook:1:1:1"]
    assert a.p_src == "" and all(c.p is None for c in a.cands)              # 没有校准表：只当证据
    sims1 = near["tbook:1:1:1"].methods[0].sims
    assert {c.char: c.evidence["b"]["hou_shape:hou"] for c in a.cands if "b" in c.evidence} == sims1
    for s in (1, 2, 3, 6):                                                  # 4d 取数处：每格 near.methods[方法名]
        assert fin[f"tbook:1:1:{s}"].near == {"hou": {"trigger": "cands",
                                                      "methods": {"hou_shape": {**trail[s], "model": sha}}}}
    assert fin["tbook:1:1:4"].near["hou"]["methods"]["hou_shape"]["error"] == "patch_missing"
    assert fin["tbook:1:1:5"].near == {}
