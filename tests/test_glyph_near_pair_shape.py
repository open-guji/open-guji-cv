"""3b `glyph_near` 的 pair_shape 方法（两字刻形二选一：史记 之矣 /1、全唐文 大太／王玉／還遺 /2，从第四步搬来，2026-11-28）。

3b 只出 `judge()` 全集当证据、sims＝σ(s)；触发、veto、nm_5b、坐标对位留在 4d。数据全在测试里造（字块图、模型同
`test_pair_shape.py`）。一致性：同一张图、同一个模型，走第四步 `seed_admit_shapes._pair_shape_pass` 与走 3b 方法，证据逐键相同。
"""
from __future__ import annotations

import json
import math
from types import SimpleNamespace as NS

import numpy as np
import pytest

from open_guji_cv.groups import near_methods as NM
from open_guji_cv.groups import pair_shape

from helpers import make_book, make_ctx, page_chars, page_match, run_steps, write_product
from test_pair_shape import _canvas, _model, _pix_model, _shift, a_img, b_img, da_img, tian_img


def _plain(v):
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    return v.tolist() if isinstance(v, np.ndarray) else v


def _multi_model():
    def feat(g):
        return pair_shape.pix_features(pair_shape.pix_ink(g))
    A = np.array([feat(da_img(False, d)) for d in (-3, 0, 3)])
    B = np.array([feat(da_img(True, d)) for d in (-3, 0, 3)])
    O = np.array([feat(tian_img())])
    means = [A.mean(0), B.mean(0), O.mean(0)]
    D = A.shape[1]
    return {"schema": pair_shape.SCHEMA_PIX, "chars": ["大", "太"], "classes": ["大", "太", "天"], "size": 32, "thr": 0.5,
            "multi": {"mu": np.zeros(D), "sd": np.ones(D), "coef": np.array([2 * m for m in means]),
                      "b": np.array([-(m @ m) for m in means])}}


@pytest.fixture
def models(tmp_path):
    """/1 之矣（HOG，护栏放开）、/1 之矣 护栏全挡、/2 大太 墨量图＋组外判别、/2 大太 多类。"""
    d = tmp_path / "groups"
    d.mkdir()
    out = {}
    for k, m in (("zy", _model()), ("zy_guard", _model(guard=0.0)), ("dt", _pix_model()), ("dt_multi", _multi_model())):
        f = d / f"pair_shape_{k}.json"
        f.write_text(json.dumps(_plain(m), ensure_ascii=False), encoding="utf-8")
        out[k] = f
    pair_shape.load.cache_clear()
    return out


IMGS = {"zy": lambda: [a_img(), b_img(), _shift(a_img(), 4), _canvas()],
        "zy_guard": lambda: [a_img(), b_img(), _canvas()],
        "dt": lambda: [da_img(), da_img(True), tian_img(), da_img(True, 3), _canvas()],
        "dt_multi": lambda: [da_img(), da_img(True), tian_img(), _canvas()]}
CHARS = {"zy": ("之", "矣"), "zy_guard": ("之", "矣"), "dt": ("大", "太"), "dt_multi": ("大", "太")}


def _spec(f, pair):
    return {"path": str(f), "pair": list(pair)}


# ── 方法：形状、写法、指纹 ──────────────────────────────────────────────

@pytest.mark.parametrize("k", sorted(IMGS))
def test_score_sims_are_sigmoid_of_score(models, k):
    a, b = CHARS[k]
    m = NM.load_method("pair_shape", _spec(models[k], (a, b)))
    assert m.patch == "char_patch" and m.chars == (a, b)
    model = pair_shape.load(str(models[k]))
    for g, o in zip(IMGS[k](), m.score(IMGS[k](), "anybook")):
        v = pair_shape.judge(g, model)
        assert o["evidence"] == {"method": "pair_shape", **v}                # judge() 全集
        if v.get("score") is None:
            assert o["sims"] == {}
        else:
            q = round(1 / (1 + math.exp(-v["score"])), 4)
            assert o["sims"] == {b: q, a: round(1 - q, 4)}
            assert not ({"other", "margin", "top", "nn"} & set(o["sims"]))  # 组外判别只进证据
            if v["char"] is not None:
                assert max(o["sims"], key=o["sims"].get) == v["char"]
        assert m.calibrate(o["sims"]) is None                                # 没有校准表：收尾不出 p


def test_abstain_kinds_and_evidence_keys(models):
    zy = NM.load_method("pair_shape", _spec(models["zy"], ("之", "矣"))).score([a_img(), _canvas()], "b")
    assert zy[0]["evidence"]["char"] == "之" and set(zy[0]["evidence"]) == {"method", "char", "why", "nn", "score"}
    assert zy[1] == {"sims": {}, "evidence": {"method": "pair_shape", "char": None, "why": "abstain:no_ink"}}
    g = NM.load_method("pair_shape", _spec(models["zy_guard"], ("之", "矣"))).score([a_img()], "b")[0]
    assert g["evidence"]["why"] == "abstain:out_of_group" and "nn" in g["evidence"] and g["sims"] == {}   # 没算出 s
    dt = NM.load_method("pair_shape", _spec(models["dt"], ("大", "太"))).score([tian_img()], "b")[0]
    assert dt["evidence"]["why"] == "abstain:out_of_group" and "other" in dt["evidence"] and dt["sims"]   # 算出了 s 仍给分
    mu = NM.load_method("pair_shape", _spec(models["dt_multi"], ("大", "太"))).score([tian_img()], "b")[0]
    assert mu["evidence"]["top"] == "天" and set(mu["evidence"]) == {"method", "char", "why", "score", "margin", "top"}


def test_spec_forms_and_fingerprint(models):
    f = models["dt"]
    m = NM.load_method("pair_shape", _spec(f, ("太", "大")))                 # 次序不论
    assert m.chars == ("大", "太") and m.model_sha == pair_shape.fingerprint(str(f))
    assert NM.method_fingerprint("pair_shape", _spec(f, ("太", "大"))) == NM.method_fingerprint("pair_shape", _spec(f, ("大", "太")))
    assert NM.method_fingerprint("pair_shape", _spec(f, ("大", "太"))) == "pair_shape=" + m.fingerprint()
    assert NM.method_fingerprint("pair_shape", str(f)) == f"pair_shape={NM._dir_fingerprint(f)}"   # 字符串写法：文件指纹
    assert NM.load_method("pair_shape", str(f)).fingerprint() == NM._dir_fingerprint(f)
    with pytest.raises(ValueError, match="大太 的模型"):
        NM.load_method("pair_shape", _spec(f, ("王", "玉")))


def test_calibrate_with_sibling_calib(models):
    f = models["dt"]
    fp0 = NM.method_fingerprint("pair_shape", _spec(f, ("大", "太")))
    (f.parent / "pair_shape_dt.calib.json").write_text(json.dumps(
        {"format": "near-calib/1", "knots": {"太": [[0.0, 1.0], [0.1, 0.9]]}}), encoding="utf-8")
    m = NM.PairShape(f, pair=["大", "太"])
    o = m.score([da_img(True)], "b")[0]
    p = m.calibrate(o["sims"])
    assert p["太"] == pytest.approx(0.1 + 0.8 * o["sims"]["太"], abs=1e-4) and p["太"] + p["大"] == pytest.approx(1.0)
    assert m.calibrate({}) is None
    assert NM.method_fingerprint("pair_shape", _spec(f, ("大", "太"))) != fp0     # 校准表进指纹


# ── 一致性：第四步现役判法 vs 3b 方法 ──────────────────────────────────

@pytest.mark.parametrize("k", sorted(IMGS))
@pytest.mark.parametrize("which", [0, 1])
def test_same_input_same_evidence_as_seed_admit_pass(models, k, which):
    """同一张图、同一个模型：第四步 `_pair_shape_pass` 写进待审格的 `evidence.pair_shape` 与 3b 方法的证据（去掉 method）逐键相同。
    格字与整理本字都是这一对里的某个字（现役会判的格）。"""
    from open_guji_cv.steps.seed_admit_shapes import _pair_shape_pass

    imgs = IMGS[k]()
    a, b = CHARS[k]
    ch = (a, b)[which]
    keys = [f"p0001c01s{i + 1}" for i in range(len(imgs))]
    ctx = NS(image=lambda kind, key: imgs[keys.index(key)])
    recs = [NS(id=f"b:1:1:{i + 1}", slot=i + 1, sub=None, char=ch, admit=False, evidence={}, provenance="match",
               channel="", doubts=[]) for i in range(len(imgs))]
    amap = {r.id: (ch,) for r in recs}
    p = NS(group_flow_pair_shape=str(models[k]), patch_missing="error")
    _pair_shape_pass(p, [NS(col=1, chars=recs)], amap, ctx, 1)
    outs = NM.load_method("pair_shape", _spec(models[k], (a, b))).score(imgs, "b")
    for r, o in zip(recs, outs):
        mine = {kk: v for kk, v in o["evidence"].items() if kk != "method"}
        assert r.evidence["pair_shape"] == mine
        if r.admit:                                                   # 现役放行了：3b 给同一个字最高分
            assert r.char == mine["char"] == ch == max(o["sims"], key=o["sims"].get)
    # 4d 比模型：书级文件＋它的两个字调同一个函数，与 3b 的 methods_sha 段相同
    assert NM.method_fingerprint("pair_shape", {"path": p.group_flow_pair_shape,
                                                "pair": pair_shape.load(str(models[k]))["chars"]}) == \
        NM.method_fingerprint("pair_shape", _spec(models[k], (b, a)))


# ── 端到端 ─────────────────────────────────────────────────────────────

def _glyph_near_step():
    from open_guji_cv.core.step import STEPS
    return STEPS["glyph_near"]


def test_glyph_near_pair_shape_end_to_end(tmp_path, models):
    from open_guji_cv.steps.glyph_near import GlyphNearParams

    groups = {"dt": {"ref": "dt", "trigger": "cands", "methods": {"pair_shape": _spec(models["dt"], ("大", "太"))}},
              "zy": {"ref": "p:之矣", "trigger": "cands", "methods": {"pair_shape": _spec(models["zy"], ("之", "矣"))}}}
    book = make_book("tbook", params={"glyph_near": {"groups": groups}, "glyph_analyzer": {"enabled": True}})
    ctx = make_ctx(tmp_path, book, raw={1: np.full((400, 300), 255, np.uint8)})
    imgs = {1: da_img(True), 2: da_img(), 3: tian_img(), 6: _canvas(), 7: a_img()}
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(recs=[
        {"slot": 1, "verdict": "unsure", "candidates": [("大", 0.90), ("太", 0.89)]},
        {"slot": 2, "verdict": "same", "char": "大", "cov": 0.95},
        {"slot": 3, "verdict": "unsure", "candidates": [("天", 0.90), ("夫", 0.8), ("大", 0.7)]},   # 组外字：3b 也跑，证据里组外
        {"slot": 4, "verdict": "unsure", "candidates": [("太", 0.90)]},             # 字块图读不到
        {"slot": 5, "verdict": "same", "char": "言", "cov": 0.95},                  # 不触发
        {"slot": 6, "verdict": "unsure", "candidates": [("太", 0.90)]},             # 空白：弃权、无分
        {"slot": 7, "verdict": "unsure", "candidates": [("之", 0.90), ("矣", 0.6)]}]))   # 之矣 组
    write_product(ctx, "cell_shrink", 1, char_index=page_chars(recs=[
        {"slot": s, "bbox_page": (30.0, 10.0 + 50 * s, 70.0, 50.0 + 50 * s), "patch_key": f"p0001c01s{s}"}
        for s in range(1, 8)]))
    for s, g in imgs.items():
        ctx.cache.put("tbook", "char_patch", f"p0001c01s{s}", g)

    p = ctx.params_for(_glyph_near_step())
    assert p.groups["dt"]["chars"] == ["大", "太"] and p.groups["zy"]["chars"] == ["之", "矣"]     # 按登记表展开
    fdt = NM.method_fingerprint("pair_shape", _spec(models["dt"], ("大", "太")))
    fzy = NM.method_fingerprint("pair_shape", _spec(models["zy"], ("之", "矣")))
    assert p.methods_sha == f"dt:{fdt};zy:{fzy}"
    assert p.methods_sha == GlyphNearParams(groups=p.groups).methods_sha

    out = run_steps(ctx, 1, ["glyph_near", "glyph_analyzer"])
    pn = out["glyph_near"]
    sdt, szy = pair_shape.fingerprint(str(models["dt"])), pair_shape.fingerprint(str(models["zy"]))
    assert pn.models == {"pair_shape:dt": sdt, "pair_shape:zy": szy}
    assert {k: [r.group for r in v] for k, v in pn.by_id_all().items()} == {
        f"tbook:1:1:{s}": [g] for s, g in ((1, "dt"), (2, "dt"), (3, "dt"), (4, "dt"), (6, "dt"), (7, "zy"))}
    mdt = pair_shape.load(str(models["dt"]))
    trail = {}
    for s in (1, 2, 3, 6):
        mo = pn.get(f"tbook:1:1:{s}", "dt").methods[0]
        assert mo.method == "pair_shape:dt"
        trail[s] = {"method": "pair_shape", **pair_shape.judge(imgs[s], mdt)}
        assert mo.evidence == trail[s]
    assert [trail[s]["char"] for s in (1, 2, 3, 6)] == ["太", "大", None, None]
    assert trail[3]["why"] == "abstain:out_of_group" and "other" in trail[3]
    assert trail[6]["why"] == "abstain:no_ink" and pn.get("tbook:1:1:6", "dt").methods[0].sims == {}
    miss = pn.get("tbook:1:1:4", "dt").methods[0]
    assert miss.sims == {} and miss.evidence["error"] == "patch_missing"
    zy7 = pn.get("tbook:1:1:7", "zy").methods[0]
    assert zy7.evidence == {"method": "pair_shape", **pair_shape.judge(imgs[7], pair_shape.load(str(models["zy"])))}
    assert zy7.evidence["char"] == "之"

    fin = out["glyph_analyzer"].by_id()
    a = fin["tbook:1:1:1"]
    assert a.p_src == "" and all(c.p is None for c in a.cands)              # 没有校准表：只当证据
    q = round(1 / (1 + math.exp(-trail[1]["score"])), 4)
    assert {c.char: c.evidence["b"]["pair_shape:dt"] for c in a.cands if "b" in c.evidence} == {"太": q, "大": round(1 - q, 4)}
    for s in (1, 2, 3, 6):                                                  # 4d 取数处：near[组].methods[方法名]
        assert fin[f"tbook:1:1:{s}"].near == {"dt": {"trigger": "cands",
                                                      "methods": {"pair_shape": {**trail[s], "model": sdt}}}}
    assert fin["tbook:1:1:7"].near["zy"]["methods"]["pair_shape"]["model"] == szy
    assert fin["tbook:1:1:4"].near["dt"]["methods"]["pair_shape"]["error"] == "patch_missing"
    assert fin["tbook:1:1:5"].near == {} and "near" not in fin["tbook:1:1:5"].model_dump(mode="json")
