"""3b `glyph_near` 的 part_shape 方法（剌刺／疎踈 等部件刻形判法从第四步搬来，照 wu_shape 样板，2026-11-28）。

书配置写 `{path, pair}`：一份模型挂多对，3b 一个组取其中一对。数据全在测试里造（字块图、权重同 `test_part_shape.py`）。
一致性：同一张图、同一个模型，走第四步 `seed_admit_shapes._part_shape_pass` 与走 3b 方法，证据逐键相同。
"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import numpy as np
import pytest

from open_guji_cv.groups import near_methods as NM
from open_guji_cv.groups import part_shape

from helpers import make_book, make_ctx, page_chars, page_match, run_steps, write_product
from test_part_shape import _glyph, _model_file, _net


def _blank():
    return np.full((120, 120), 255, np.uint8)


def _glyph2():
    g = _glyph()
    return np.ascontiguousarray(g[:, ::-1])


def _imgs():
    return [_glyph(), _glyph2(), _blank()]


PAIRS = {"ci": ("剌", "刺"), "shu": ("疎", "踈"), "zan": ("攢", "攅"), "rnd": ("甲", "申")}


@pytest.fixture
def model(tmp_path):
    """一份挂四对：剌刺 判 刺（偏置 +8）、疎踈 判 疎（−8）、攢攅 p＝0.5 弃权（全零）、甲申 随机权重。"""
    d = tmp_path / "groups"
    d.mkdir()
    return _model_file(d, [(PAIRS["ci"], [0, 0.65, 0, 1], 0.95, _net(bias=8.0)),
                           (PAIRS["shu"], [0, 0.5, 0, 0.6], 0.95, _net(bias=-8.0)),
                           (PAIRS["zan"], [0, 1, 0, 1], 0.95, _net(zero=True)),
                           (PAIRS["rnd"], [0.3, 1, 0, 1], 0.6, _net(seed=3))])


def _spec(f, pair):
    return {"path": str(f), "pair": list(pair)}


# ── 方法：形状、写法、指纹 ──────────────────────────────────────────────

def test_score_shapes_and_no_calib(model):
    for k, want in (("ci", "刺"), ("shu", "疎"), ("zan", None)):
        m = NM.load_method("part_shape", _spec(model, PAIRS[k]))
        assert m.patch == "char_patch" and m.chars == PAIRS[k]
        o, o2, blank = m.score(_imgs(), "anybook")
        a, b = PAIRS[k]
        assert o["evidence"]["method"] == "part_shape" and o["evidence"]["char"] == want
        assert o["evidence"]["pair"] == a + b
        assert set(o["sims"]) == {a, b} and o["sims"][b] == o["evidence"]["p"]                # p 是 chars[1] 的概率
        assert o["sims"][a] + o["sims"][b] == pytest.approx(1.0, abs=1e-9)
        if want:
            assert max(o["sims"], key=o["sims"].get) == want
        else:
            assert o["evidence"]["why"] == "abstain:low_p"                 # 门槛中间仍给分，弃权记在证据里
        assert blank == {"sims": {}, "evidence": {"method": "part_shape", "char": None, "why": "abstain:no_ink",
                                                  "pair": a + b}}
        assert all(m.calibrate(x["sims"]) is None for x in (o, o2, blank))   # 没有校准表：收尾不出 p


def test_spec_forms_and_errors(model, tmp_path):
    m1 = NM.load_method("part_shape", _spec(model, ("剌", "刺")))
    m2 = NM.load_method("part_shape", _spec(model, ("刺", "剌")))          # 次序不论，方向按模型
    assert m2.chars == ("剌", "刺") and m1.fingerprint() == m2.fingerprint()
    with pytest.raises(ValueError, match="挂了 4 对"):
        NM.load_method("part_shape", str(model))                           # 多对文件不写 pair
    with pytest.raises(ValueError, match="没有"):
        NM.load_method("part_shape", _spec(model, ("天", "夭")))
    with pytest.raises(ValueError, match="不认识"):
        NM.load_method("part_shape", {"path": str(model), "pair": ["剌", "刺"], "x": 1})
    with pytest.raises(TypeError):
        NM.load_method("wu_shape", {"path": str(model), "pair": ["嗚", "鳴"]})      # 不收 pair 的方法
    one = _model_file(tmp_path, [(PAIRS["ci"], [0, 0.65, 0, 1], 0.95, _net(bias=8.0))], name="one.json")
    m = NM.load_method("part_shape", str(one))                             # 只挂一对：字符串也行
    assert m.chars == ("剌", "刺") and m.fingerprint() == NM._dir_fingerprint(one)
    assert NM.method_fingerprint("part_shape", str(one)) == f"part_shape={NM._dir_fingerprint(one)}"


def test_method_fingerprint_by_path_and_pair(model):
    fa = NM.method_fingerprint("part_shape", _spec(model, ("剌", "刺")))
    assert fa == NM.method_fingerprint("part_shape", _spec(model, ("刺", "剌")))
    assert fa != NM.method_fingerprint("part_shape", _spec(model, ("疎", "踈")))          # 换一对换指纹
    assert fa == "part_shape=" + NM.load_method("part_shape", _spec(model, ("剌", "刺"))).fingerprint()
    assert NM.load_method("part_shape", _spec(model, ("剌", "刺"))).model_sha == part_shape.fingerprint(str(model))
    # 字符串写法的指纹与之前逐位相同（不受 {path, pair} 影响）
    assert NM.method_fingerprint("wu_shape", str(model)) == f"wu_shape={NM._dir_fingerprint(model)}"
    (model.parent / "part_shape.calib.json").write_text(json.dumps({"format": "near-calib/1", "knots": {}}),
                                                        encoding="utf-8")
    assert NM.method_fingerprint("part_shape", _spec(model, ("剌", "刺"))) != fa            # 校准表进指纹


def test_calibrate_with_sibling_calib(model):
    (model.parent / "part_shape.calib.json").write_text(json.dumps(
        {"format": "near-calib/1", "knots": {"申": [[0.0, 1.0], [0.1, 0.9]]}}), encoding="utf-8")
    m = NM.PartShape(model, pair=["甲", "申"])
    o = m.score([_glyph()], "b")[0]
    p = m.calibrate(o["sims"])
    assert p["申"] == pytest.approx(0.1 + 0.8 * o["sims"]["申"], abs=1e-4) and p["申"] + p["甲"] == pytest.approx(1.0)
    assert NM.PartShape(model, pair=["剌", "刺"]).calibrate({"刺": 0.5, "剌": 0.5}) is None    # 别的对没有 knots
    assert m.calibrate({}) is None


# ── 一致性：第四步现役判法 vs 3b 方法 ──────────────────────────────────

@pytest.mark.parametrize("k", sorted(PAIRS))
@pytest.mark.parametrize("admitted", [False, True])
def test_same_input_same_evidence_as_seed_admit_pass(model, k, admitted):
    """同一张图、同一个模型：第四步 `_part_shape_pass` 写进格的 `evidence.part_shape` 与 3b 方法的证据（去掉 method）逐键相同。"""
    from open_guji_cv.steps.seed_admit_shapes import _part_shape_pass

    imgs = _imgs()
    a, b = PAIRS[k]
    keys = [f"p0001c01s{i + 1}" for i in range(len(imgs))]
    ctx = NS(image=lambda kind, key: imgs[keys.index(key)])
    recs = [NS(id=f"b:1:1:{i + 1}", slot=i + 1, sub=None, char=a, admit=admitted, evidence={},
               provenance="match", channel="match_ref" if admitted else "", doubts=[]) for i in range(len(imgs))]
    p = NS(group_flow_part_shape=str(model), patch_missing="error")
    _part_shape_pass(p, [NS(col=1, chars=recs)], {}, ctx, 1)
    outs = NM.load_method("part_shape", _spec(model, PAIRS[k])).score(imgs, "b")
    pair = part_shape.pair_of(part_shape.load(str(model)), a)
    for r, o, g in zip(recs, outs, imgs):
        mine = {kk: v for kk, v in o["evidence"].items() if kk != "method"}
        assert mine == part_shape.judge(g, pair)
        if "part_shape" in r.evidence:                                # 现役记了（待审格全记；已放行格只在改字时记）
            assert r.evidence["part_shape"] == mine
        else:
            assert admitted and mine["char"] in (None, a)
        if mine["char"] is not None:                                  # 现役定了字：3b 给同一个字最高分
            assert r.char == mine["char"] == max(o["sims"], key=o["sims"].get)
            assert r.admit
        else:
            assert r.admit == admitted and r.char == a
    # 4d 比模型：本格那一对＋书级 group_flow_part_shape 调同一个函数，与 3b 的 methods_sha 段相同
    assert NM.method_fingerprint("part_shape", {"path": p.group_flow_part_shape, "pair": pair["chars"]}) == \
        NM.method_fingerprint("part_shape", _spec(model, PAIRS[k]))


# ── 端到端 ─────────────────────────────────────────────────────────────

def _glyph_near_step():
    from open_guji_cv.core.step import STEPS
    return STEPS["glyph_near"]


def test_glyph_near_part_shape_end_to_end(tmp_path, model):
    from open_guji_cv.steps.glyph_near import GlyphNearParams

    groups = {"ci": {"ref": "ci", "trigger": "cands", "methods": {"part_shape": _spec(model, ("剌", "刺"))}},
              "shu": {"ref": "p:疎踈", "trigger": "cands", "methods": {"part_shape": _spec(model, ("疎", "踈"))}}}
    book = make_book("tbook", params={"glyph_near": {"groups": groups}, "glyph_analyzer": {"enabled": True}})
    ctx = make_ctx(tmp_path, book, raw={1: np.full((400, 300), 255, np.uint8)})
    imgs = {1: _glyph(), 2: _glyph2(), 3: _glyph(), 6: _blank(), 7: _glyph()}
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(recs=[
        {"slot": 1, "verdict": "unsure", "candidates": [("剌", 0.90), ("刺", 0.89)]},
        {"slot": 2, "verdict": "same", "char": "刺", "cov": 0.95},
        {"slot": 3, "verdict": "unsure", "candidates": [("束", 0.90), ("敕", 0.8), ("刺", 0.7)]},   # 首位不在组里：3b 也跑，4d 不读
        {"slot": 4, "verdict": "unsure", "candidates": [("剌", 0.90)]},             # 字块图读不到
        {"slot": 5, "verdict": "same", "char": "言", "cov": 0.95},                  # 不触发
        {"slot": 6, "verdict": "unsure", "candidates": [("刺", 0.90)]},             # 空白：弃权、无分
        {"slot": 7, "verdict": "unsure", "candidates": [("踈", 0.90), ("剌", 0.85)]}]))   # 两组都触发
    write_product(ctx, "cell_shrink", 1, char_index=page_chars(recs=[
        {"slot": s, "bbox_page": (30.0, 10.0 + 50 * s, 70.0, 50.0 + 50 * s), "patch_key": f"p0001c01s{s}"}
        for s in range(1, 8)]))
    for s, g in imgs.items():
        ctx.cache.put("tbook", "char_patch", f"p0001c01s{s}", g)

    p = ctx.params_for(_glyph_near_step())
    assert p.groups["ci"]["chars"] == ["刺", "剌"] and p.groups["shu"]["chars"] == ["疎", "踈"]   # 按登记表展开
    fci = NM.method_fingerprint("part_shape", _spec(model, ("剌", "刺")))
    fshu = NM.method_fingerprint("part_shape", _spec(model, ("疎", "踈")))
    assert p.methods_sha == f"ci:{fci};shu:{fshu}" and fci != fshu
    assert p.methods_sha == GlyphNearParams(groups=p.groups).methods_sha

    out = run_steps(ctx, 1, ["glyph_near", "glyph_analyzer"])
    pn = out["glyph_near"]
    sha = part_shape.fingerprint(str(model))                                # 与第四步参数指纹 pt 段同算法
    assert pn.models == {"part_shape:ci": sha, "part_shape:shu": sha}
    full = part_shape.load(str(model))
    trail = {}
    for s in (1, 2, 3, 6, 7):
        mo = pn.get(f"tbook:1:1:{s}", "ci").methods[0]
        assert mo.method == "part_shape:ci"
        trail[s] = {"method": "part_shape", **part_shape.judge(imgs[s], part_shape.pair_of(full, "剌"))}
        assert mo.evidence == trail[s]
    assert [trail[s]["char"] for s in (1, 2, 3, 6, 7)] == ["刺", "刺", "刺", None, "刺"]
    assert trail[6]["why"] == "abstain:no_ink" and pn.get("tbook:1:1:6", "ci").methods[0].sims == {}
    miss = pn.get("tbook:1:1:4", "ci").methods[0]
    assert miss.sims == {} and miss.evidence["error"] == "patch_missing"
    shu7 = pn.get("tbook:1:1:7", "shu").methods[0]                         # 同一格另一组：另一对
    assert shu7.evidence == {"method": "part_shape", **part_shape.judge(imgs[7], part_shape.pair_of(full, "疎"))}
    assert shu7.evidence["char"] == "疎" and set(shu7.sims) == {"疎", "踈"}
    assert [r.group for r in pn.by_id_all()["tbook:1:1:7"]] == ["ci", "shu"] and pn.get("tbook:1:1:1", "shu") is None

    fin = out["glyph_analyzer"].by_id()
    a = fin["tbook:1:1:1"]
    assert a.p_src == "" and all(c.p is None for c in a.cands)              # 没有校准表：只当证据
    assert {c.char: c.evidence["b"]["part_shape:ci"] for c in a.cands if "b" in c.evidence} == {
        "刺": trail[1]["p"], "剌": round(1 - trail[1]["p"], 4)}
    for s in (1, 2, 3, 6):                                                  # 4d 取数处：near[组].methods[方法名]
        assert fin[f"tbook:1:1:{s}"].near == {"ci": {"trigger": "cands",
                                                      "methods": {"part_shape": {**trail[s], "model": sha}}}}
    assert set(fin["tbook:1:1:7"].near) == {"ci", "shu"}
    assert fin["tbook:1:1:4"].near["ci"]["methods"]["part_shape"]["error"] == "patch_missing"
    assert fin["tbook:1:1:5"].near == {} and "near" not in fin["tbook:1:1:5"].model_dump(mode="json")
