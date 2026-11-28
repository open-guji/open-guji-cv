"""3b `glyph_near` 的 stroke_veto 方法（己／已巳、千／干 笔画反向护栏的看图判法从第四步搬来，照 part_shape 样板，2026-11-28）。

书配置写 `{path, group}`：一份模型挂几组，3b 一个组取其中一组。数据全在测试里造：字块图用 cv2 画（己 左上留缺口、已巳 左竖通顶；
千 首笔斜撇、干 首横平），通用模板用 `from_polylines` 现造，模型用 `stroke_veto.build` 在这些图上学——**不顶替 `features`／`judge`**，
走真的配准与量法。一致性：同一张图、同一个模型，走第四步 `seed_admit_shapes._stroke_veto_pass` 与走 3b 方法，证据逐键相同。
"""
from __future__ import annotations

import json
import math
from types import SimpleNamespace as NS

import numpy as np
import pytest

from open_guji_cv.groups import near_methods as NM
from open_guji_cv.groups import stroke_veto as sv

from helpers import make_book, make_ctx, page_chars, page_match, run_steps, write_product
from test_groups_strokes import glyph as _qg_glyph

cv2 = pytest.importorskip("cv2")


# ── 造图、造模型 ───────────────────────────────────────────────────────

def _jys_glyph(ch: str, dx: int = 0, dy: int = 0, top: int | None = None) -> np.ndarray:
    """己：左竖从中横起（左上留缺口）；已／巳：左竖通到顶横。`top` 直接给左竖起点（中间态）。"""
    g = np.full((80, 80), 255, np.uint8)

    def o(x, y):
        return (x + dx, y + dy)
    cv2.line(g, o(18, 12), o(62, 12), 0, 4)
    cv2.line(g, o(62, 12), o(62, 42), 0, 4)
    cv2.line(g, o(18, 42), o(62, 42), 0, 4)
    t = top if top is not None else (12 if ch in "已巳" else 42)
    cv2.line(g, o(18, t), o(18, 68), 0, 4)
    cv2.line(g, o(18, 68), o(66, 68), 0, 4)
    cv2.line(g, o(66, 68), o(66, 58), 0, 4)
    return g


def _shift(g: np.ndarray, dx: int, dy: int) -> np.ndarray:
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(g, m, (g.shape[1], g.shape[0]), borderValue=255)


def _blank():
    return np.full((80, 80), 255, np.uint8)


def _templates():
    from open_guji_cv.strokes.template import from_polylines
    si = from_polylines("巳", [("横折", np.array([[12, 18], [12, 62], [42, 62.0]])), ("横", np.array([[42, 18], [42, 62.0]])),
                              ("竖弯钩", np.array([[12, 18], [68, 18], [68, 66], [58, 66.0]]))])
    gan = from_polylines("干", [("横", np.array([[11, 18], [11, 60.0]])), ("横", np.array([[34, 4], [34, 76.0]])),
                               ("竖", np.array([[10, 40], [70, 40.0]]))])
    return {"jys": si, "qg": gan}


def _samples():
    shifts = [(dx, dy) for dx in (-2, 0, 2) for dy in (-2, 0, 2)]
    jys = [(_jys_glyph("己", dx, dy), "己") for dx, dy in shifts]
    jys += [(_jys_glyph("已", dx, dy), "已") for dx, dy in shifts[:5]] + [(_jys_glyph("巳", dx, dy), "巳") for dx, dy in shifts[4:]]
    qg = [(_shift(_qg_glyph(ch), dx, dy), ch) for ch in "千干" for dx, dy in shifts]
    return {"jys": jys, "qg": qg}


@pytest.fixture(scope="module")
def models(tmp_path_factory):
    """一份挂两组（jys、qg）的书级模型，几个变体：
    base（t=3、max_z=6，同书里的缺省）；hi_t（t 极大：凡算出似然比的格都弃权 `abstain`）；no_z（不设 max_z）；
    ch（jys 只看 group_flow 放行的格，现役的 `channels`）；one（只挂 qg 一组）。"""
    d = tmp_path_factory.mktemp("sv")
    base = sv.build(_samples(), _templates(), t=3.0, max_z=6.0)
    out = {}
    for k, edit in (("base", lambda m: m), ("hi_t", lambda m: _set(m, t=1e6)), ("no_z", lambda m: _set(m, max_z=None)),
                    ("ch", lambda m: {**m, "groups": {**m["groups"], "jys": {**m["groups"]["jys"], "channels": ["group_flow"]}}}),
                    ("one", lambda m: {**m, "groups": {"qg": m["groups"]["qg"]}})):
        sub = d / k
        sub.mkdir()
        f = sub / "stroke_veto.json"
        f.write_text(json.dumps(edit(json.loads(json.dumps(base))), ensure_ascii=False), encoding="utf-8")
        out[k] = f
    return out


def _set(m, **kw):
    return {**m, "groups": {g: {**gm, **kw} for g, gm in m["groups"].items()}}


def _imgs(group: str) -> list[np.ndarray]:
    """jys：己、已、巳、左竖起在半当中（中间态）、空白；qg：千、干、于（组外字）、空白。"""
    if group == "jys":
        return [_jys_glyph("己", 1, 0), _jys_glyph("已", 0, 1), _jys_glyph("巳", -1, -1), _jys_glyph("己", top=27), _blank()]
    return [_shift(_qg_glyph("千"), 1, 0), _shift(_qg_glyph("干"), 0, 1), _qg_glyph("于"), _blank()]


def _spec(f, group):
    return {"path": str(f), "group": group}


def _sig(x):
    return round(1.0 / (1.0 + math.exp(-float(x))), 4)


# ── 方法：形状、sims ───────────────────────────────────────────────────

def test_real_judge_covers_all_outcomes(models):
    """造的图在真判法下各档都有：判 己、判 已巳、判 千、判 干、离群 out、贴坏 bad_fit；hi_t 下凡有似然比的都是 abstain。"""
    got = {}
    for g in ("jys", "qg"):
        gm = sv.load(str(models["base"]))["groups"][g]
        got[g] = [sv.judge(im, gm) for im in _imgs(g)]
    assert [v["cls"] for v in got["jys"][:3]] == ["己", "已巳", "已巳"]
    assert [v["cls"] for v in got["qg"][:2]] == ["千", "干"]
    assert got["jys"][-1] == {"cls": None, "why": "bad_fit"} and got["qg"][-1] == {"cls": None, "why": "bad_fit"}
    assert {v["why"] for v in got["jys"] + got["qg"]} >= {"llr", "out", "bad_fit"}
    hi = sv.load(str(models["hi_t"]))["groups"]["jys"]
    assert [sv.judge(im, hi)["why"] for im in _imgs("jys")[:3]] == ["abstain"] * 3


@pytest.mark.parametrize("k", ["base", "hi_t", "no_z"])
@pytest.mark.parametrize("group", ["jys", "qg"])
def test_score_evidence_is_judge_and_sims_follow_it(models, k, group):
    m = NM.load_method("stroke_veto", _spec(models[k], group))
    assert m.patch == "char_patch" and m.group == group
    gm = sv.load(str(models[k]))["groups"][group]
    chars = set(gm["classes"])
    imgs = _imgs(group)
    for im, o in zip(imgs, m.score(imgs, "anybook")):
        v = sv.judge(im, gm)
        assert o["evidence"] == {"method": "stroke_veto", "group": group, **v}                 # judge 原样，外加 method、group
        assert list(o["evidence"])[2:] == list(v)                                              # 键次序也同
        if v.get("llr") is None:                                                               # out／bad_fit：没有似然比 → 无分
            assert o["sims"] == {} and v["why"] in ("out", "bad_fit")
            continue
        sims = o["sims"]
        assert set(sims) == chars
        top = max(sims.values())
        assert top == _sig(v["llr"]) and min(sims.values()) == round(1 - top, 4)
        lead = {gm["classes"][c] for c, s in sims.items() if s == top}
        if v["cls"] is not None:                                                               # 判出了类：最高分＝现役判出的类
            assert lead == {v["cls"]} and top >= _sig(gm.get("t", 3.0)) - 1e-4
        else:                                                                                  # 似然比不够：方向按对数似然
            assert v["why"] == "abstain" and 0.5 <= top < _sig(gm["t"]) + 1e-4
            ll = gm["_stats"].loglik(sv.features(im, gm)[0])
            assert lead == {max(ll, key=ll.get)}
        if group == "jys":
            assert sims["已"] == sims["巳"]                                                     # 合类同分（方法分不开，不是归一）
    assert all(m.calibrate(o["sims"]) is None for o in m.score(imgs, "b"))                    # 没有校准表：收尾不出 p


def test_spec_forms_and_errors(models, tmp_path):
    with pytest.raises(ValueError, match="挂了 2 组"):
        NM.load_method("stroke_veto", str(models["base"]))                                   # 多组文件不写 group
    with pytest.raises(ValueError, match="没有组"):
        NM.load_method("stroke_veto", _spec(models["base"], "mu"))
    with pytest.raises(ValueError, match="不认识"):
        NM.load_method("stroke_veto", {"path": str(models["base"]), "group": "jys", "pair": ["己", "已"]})
    with pytest.raises(TypeError):
        NM.load_method("wu_shape", {"path": str(models["base"]), "group": "jys"})            # 不收 group 的方法
    m = NM.load_method("stroke_veto", str(models["one"]))                                    # 只挂一组：字符串也行
    assert m.group == "qg" and m.fingerprint() == NM._dir_fingerprint(models["one"])
    assert NM.method_fingerprint("stroke_veto", str(models["one"])) == f"stroke_veto={NM._dir_fingerprint(models['one'])}"
    d = tmp_path / "svdir"
    d.mkdir()
    (d / "model.json").write_bytes(models["one"].read_bytes())
    m = NM.load_method("stroke_veto", str(d))                                                # 目录写法
    assert m.model_sha == sv.fingerprint(str(d / "model.json")) and m.fingerprint() == NM._dir_fingerprint(d)
    three = json.loads(models["base"].read_text(encoding="utf-8"))
    three["groups"]["jys"]["classes"] = {"己": "己", "已": "已", "巳": "巳"}
    f3 = tmp_path / "three.json"
    f3.write_text(json.dumps(three, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="只认两类"):
        NM.StrokeVeto(f3, group="jys")


def test_method_fingerprint_by_path_and_group(models, tmp_path):
    from open_guji_cv.steps.seed_admit_params import SeedAdmitParams

    f = models["base"]
    fj, fq = (NM.method_fingerprint("stroke_veto", _spec(f, g)) for g in ("jys", "qg"))
    assert fj != fq                                                                          # 换一组换指纹
    assert fj == "stroke_veto=" + NM.load_method("stroke_veto", _spec(f, "jys")).fingerprint()
    sha = NM.load_method("stroke_veto", _spec(f, "jys")).model_sha
    assert sha == sv.fingerprint(str(f)) == SeedAdmitParams(stroke_veto=str(f)).stroke_veto_fingerprint   # 与第四步参数指纹同值
    # 字符串写法的指纹与之前逐位相同（不受 {path, group} 影响）；{path} 不带 group 也同字符串
    assert NM.method_fingerprint("hou_shape", str(f)) == f"hou_shape={NM._dir_fingerprint(f)}"
    assert NM.method_fingerprint("stroke_veto", {"path": str(f)}) == NM.method_fingerprint("stroke_veto", str(f))
    g = tmp_path / "copy.json"
    g.write_bytes(f.read_bytes())
    (tmp_path / "copy.calib.json").write_text(json.dumps({"format": "near-calib/1", "knots": {}}), encoding="utf-8")
    assert NM.method_fingerprint("stroke_veto", _spec(g, "jys")) != fj                       # 校准表进指纹


def test_calibrate_only_for_single_char_classes(models, tmp_path):
    g = tmp_path / "sv.json"
    g.write_bytes(models["base"].read_bytes())
    (tmp_path / "sv.calib.json").write_text(json.dumps(
        {"format": "near-calib/1", "knots": {"干": [[0.0, 1.0], [0.1, 0.9]], "己": [[0.0, 1.0], [0.0, 1.0]]}}), encoding="utf-8")
    mq = NM.StrokeVeto(g, group="qg")
    o = mq.score([_shift(_qg_glyph("干"), 0, 1)], "b")[0]
    p = mq.calibrate(o["sims"])
    assert p["干"] == pytest.approx(0.1 + 0.8 * o["sims"]["干"], abs=1e-4) and p["干"] + p["千"] == pytest.approx(1.0)
    assert mq.calibrate({}) is None
    mj = NM.StrokeVeto(g, group="jys")                                                       # 已巳 合类：各字 p 分不开 → None
    assert mj.calibrate(mj.score([_jys_glyph("己")], "b")[0]["sims"]) is None


# ── 一致性：第四步现役判法 vs 3b 方法 ──────────────────────────────────

@pytest.mark.parametrize("k", ["base", "hi_t", "no_z", "ch"])
@pytest.mark.parametrize("group,admitted_as", [("jys", "己"), ("jys", "已"), ("jys", "巳"), ("qg", "千"), ("qg", "干")])
def test_same_input_same_evidence_as_seed_admit_pass(models, k, group, admitted_as):
    """同一批图、同一个模型：`_stroke_veto_pass` 给已放行格写的 `evidence.stroke_veto` 与 `stroke_veto_trail(3b 证据)` 逐键相等；
    降不降审＝「3b 判出了类且≠放行字的类」；判同字、弃权（abstain／out／bad_fit）现役都不动。`channels` 只是现役挑格，3b 证据不受影响。"""
    from open_guji_cv.steps.seed_admit_shapes import _stroke_veto_pass

    imgs = _imgs(group)
    keys = [f"p0001c01s{i + 1}" for i in range(len(imgs))]
    ctx = NS(image=lambda kind, key: imgs[keys.index(key)])
    recs = [NS(id=f"b:1:1:{i + 1}", slot=i + 1, sub=None, char=admitted_as, admit=True, evidence={}, provenance="match",
               channel="match_ref", doubts=[]) for i in range(len(imgs))]
    p = NS(stroke_veto=str(models[k]), patch_missing="error")
    n = _stroke_veto_pass(p, [NS(col=1, chars=recs)], ctx, 1)
    gm = sv.load(str(models[k]))["groups"][group]
    outs = NM.load_method("stroke_veto", _spec(models[k], group)).score(imgs, "b")
    gate = not gm.get("channels") or "match_ref" in gm["channels"]
    seen = set()
    for r, o, im in zip(recs, outs, imgs):
        ev = o["evidence"]
        assert {kk: v for kk, v in ev.items() if kk not in ("method", "group")} == sv.judge(im, gm)
        flips = ev["cls"] is not None and ev["cls"] != gm["classes"][admitted_as]
        if gate and flips:                                                                    # 判另一字：降审，证据逐键相等
            assert not r.admit and "stroke_veto" in r.doubts
            assert r.evidence["stroke_veto"] == NM.stroke_veto_trail(ev)
            assert list(r.evidence["stroke_veto"]) == list(NM.stroke_veto_trail(ev))
            assert max(o["sims"], key=o["sims"].get) in {c for c, v in gm["classes"].items() if v == ev["cls"]}
            seen.add("flip")
        else:                                                                                 # 判同字／弃权／通道不看：不动
            assert r.admit and r.char == admitted_as and "stroke_veto" not in r.evidence
            seen.add("same" if ev["cls"] is not None else "abstain")
    assert n == sum(not r.admit for r in recs)
    if k == "base":                                                                           # 三种情形都覆盖到
        assert seen == {"flip", "same", "abstain"}


def test_trail_fills_missing_keys_with_none():
    """现役 `{"group": gid, "cls": v["cls"], "llr": v.get("llr"), "x": v.get("x")}`：judge 没给 llr／x 时记 None。"""
    assert NM.stroke_veto_trail({"method": "stroke_veto", "group": "qg", "cls": "干", "why": "llr", "llr": 7.1, "x": [0.1]}) == \
        {"group": "qg", "cls": "干", "llr": 7.1, "x": [0.1]}
    assert NM.stroke_veto_trail({"method": "stroke_veto", "group": "qg", "cls": None, "why": "bad_fit"}) == \
        {"group": "qg", "cls": None, "llr": None, "x": None}


# ── 端到端 ─────────────────────────────────────────────────────────────

def _glyph_near_step():
    from open_guji_cv.core.step import STEPS
    return STEPS["glyph_near"]


def test_glyph_near_stroke_veto_end_to_end(tmp_path, models):
    from open_guji_cv.steps.glyph_near import GlyphNearParams

    mf = models["base"]
    groups = {"jys": {"ref": "jys", "trigger": "cands", "methods": {"stroke_veto": _spec(mf, "jys")}},
              "qg": {"ref": "zy", "chars": ["千", "干"], "trigger": "cands", "methods": {"stroke_veto": _spec(mf, "qg")}}}
    book = make_book("tbook", params={"glyph_near": {"groups": groups}, "glyph_analyzer": {"enabled": True}})
    ctx = make_ctx(tmp_path, book, raw={1: np.full((500, 300), 255, np.uint8)})
    jys_i, qg_i = _imgs("jys"), _imgs("qg")
    imgs = {1: jys_i[0], 2: jys_i[1], 3: qg_i[1], 4: jys_i[0], 6: _blank(), 8: qg_i[0]}
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(recs=[
        {"slot": 1, "verdict": "unsure", "candidates": [("己", 0.90), ("已", 0.89)]},
        {"slot": 2, "verdict": "same", "char": "已", "cov": 0.95},
        {"slot": 3, "verdict": "unsure", "candidates": [("言", 0.90), ("文", 0.8), ("干", 0.7)]},   # 首位不在组里：前 topk 有 干，也跑
        {"slot": 4, "verdict": "unsure", "candidates": [("己", 0.90)]},             # 字块图读不到
        {"slot": 5, "verdict": "same", "char": "言", "cov": 0.95},                  # 不触发
        {"slot": 6, "verdict": "unsure", "candidates": [("巳", 0.90)]},             # 空白：bad_fit、无分
        {"slot": 7, "verdict": "same", "char": "于", "cov": 0.95},                  # 于 被 chars 盖掉了：不触发
        {"slot": 8, "verdict": "unsure", "candidates": [("千", 0.90), ("己", 0.85)]}]))   # 两组都触发
    write_product(ctx, "cell_shrink", 1, char_index=page_chars(recs=[
        {"slot": s, "bbox_page": (30.0, 10.0 + 50 * s, 70.0, 50.0 + 50 * s), "patch_key": f"p0001c01s{s}"}
        for s in range(1, 9)]))
    for s, g in imgs.items():
        if s != 4:
            ctx.cache.put("tbook", "char_patch", f"p0001c01s{s}", g)

    p = ctx.params_for(_glyph_near_step())
    assert p.groups["jys"]["chars"] == ["己", "已", "巳"] and p.groups["qg"]["chars"] == ["千", "干"]   # 按登记表展开
    fj, fq = (NM.method_fingerprint("stroke_veto", _spec(mf, g)) for g in ("jys", "qg"))
    assert p.methods_sha == f"jys:{fj};qg:{fq}" == GlyphNearParams(groups=p.groups).methods_sha

    out = run_steps(ctx, 1, ["glyph_near", "glyph_analyzer"])
    pn = out["glyph_near"]
    sha = sv.fingerprint(str(mf))                                                    # 与第四步参数指纹 stroke_veto_fingerprint 同值
    assert pn.models == {"stroke_veto:jys": sha, "stroke_veto:qg": sha}
    allr = pn.by_id_all()
    assert {k: [r.group for r in v] for k, v in allr.items()} == {
        "tbook:1:1:1": ["jys"], "tbook:1:1:2": ["jys"], "tbook:1:1:3": ["qg"], "tbook:1:1:4": ["jys"],
        "tbook:1:1:6": ["jys"], "tbook:1:1:8": ["jys", "qg"]}
    model = sv.load(str(mf))
    trail = {}
    for s, g in ((1, "jys"), (2, "jys"), (3, "qg"), (6, "jys"), (8, "jys"), (8, "qg")):
        rec = pn.get(f"tbook:1:1:{s}", g)                                            # 4d 的取法：get(格 id, 组)
        (mo,) = rec.methods
        assert mo.method == f"stroke_veto:{g}" and rec.trigger == "cands"
        trail[(s, g)] = {"method": "stroke_veto", "group": g, **sv.judge(imgs[s], model["groups"][g])}
        assert mo.evidence == trail[(s, g)]
    assert [trail[k]["cls"] for k in ((1, "jys"), (2, "jys"), (3, "qg"), (6, "jys"), (8, "qg"))] == \
        ["己", "已巳", "干", None, "千"]
    assert pn.get("tbook:1:1:6", "jys").methods[0].sims == {}
    miss = pn.get("tbook:1:1:4", "jys").methods[0]
    assert miss.sims == {} and miss.evidence["error"] == "patch_missing"

    fin = out["glyph_analyzer"].by_id()
    a = fin["tbook:1:1:1"]
    assert a.p_src == "" and all(c.p is None for c in a.cands)                       # 没有校准表：只当证据
    sims1 = pn.get("tbook:1:1:1", "jys").methods[0].sims
    assert {c.char: c.evidence["b"]["stroke_veto:jys"] for c in a.cands if "b" in c.evidence} == sims1
    for (s, g), t in trail.items():                                                  # 4d 取数处：每格 near[组].methods.stroke_veto
        assert fin[f"tbook:1:1:{s}"].near[g] == {"trigger": "cands", "methods": {"stroke_veto": {**t, "model": sha}}}
    assert fin["tbook:1:1:4"].near["jys"]["methods"]["stroke_veto"]["error"] == "patch_missing"
    assert fin["tbook:1:1:5"].near == {} and fin["tbook:1:1:7"].near == {}
