"""3b `glyph_near` 的 rr_shape 方法（入人八 书级刻形判法从第四步搬来的样板，2026-11-28）＋方法接口的可选 ctx＋书配置 `ref`。

数据全在测试里造（字块图、模型同 `test_rr_shape.py`）。一致性：同一张图走第四步 `seed_admit_shapes._rr_shape_pass`
与走 3b 方法，证据逐键相同。
"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import numpy as np
import pytest

from open_guji_cv.groups import near_methods as NM
from open_guji_cv.groups import rr_shape

from helpers import make_book, make_ctx, page_chars, page_match, run_steps, write_product
from test_rr_shape import _model, _shift, ba, ren, ru


def _imgs():
    rens = [_shift(ren(), d) for d in (-3, 0, 3)]
    rus = [_shift(ru(), d) for d in (-3, 0, 3)]
    return rens, rus


def _write_model(path, **kw):
    rens, rus = _imgs()
    m = _model(rens + rus + [ba()], rens, rus, **kw)
    path.write_text(json.dumps({k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in m.items()}),
                    encoding="utf-8")
    return path


@pytest.fixture
def model_file(tmp_path):
    d = tmp_path / "groups"
    d.mkdir()
    return _write_model(d / "rr_shape.json")


def _blank():
    return np.full((120, 120), 255, np.uint8)


def _probe_imgs():
    """几何判 八、逻辑回归 人／入、挪了位的、空白（无墨弃权）。"""
    return [ba(), ren(), ru(), _shift(ren(), 5), _shift(ru(), -5), _blank()]


# ── 方法：形状 ─────────────────────────────────────────────────────────

def test_score_shapes_and_no_calib(model_file):
    m = NM.load_method("rr_shape", str(model_file))
    assert m.patch == "char_patch"
    outs = m.score(_probe_imgs(), "anybook")
    assert len(outs) == 6
    b, r, u = outs[0], outs[1], outs[2]
    assert b["sims"] == {"八": 1.0, "人": 0.0, "入": 0.0} and b["evidence"]["char"] == "八"
    assert r["evidence"]["char"] == "人" and r["sims"]["人"] > 0.5 > r["sims"]["入"] and r["sims"]["八"] == 0.0
    assert u["evidence"]["char"] == "入" and u["sims"]["入"] > 0.5
    for o in (r, u):
        assert o["sims"]["人"] + o["sims"]["入"] == pytest.approx(1.0, abs=1e-4)
    assert outs[5]["sims"] == {} and outs[5]["evidence"]["why"] == "abstain:no_ink"
    assert all(m.calibrate(o["sims"]) is None for o in outs)          # 没有校准表：收尾不出 p


def test_abstain_kinds(tmp_path):
    rens, _ = _imgs()
    m = NM.load_method("rr_shape", str(_write_model(tmp_path / "g.json", guard=0.0)))
    o = m.score([rens[1]], "b")[0]
    assert o["sims"] == {} and o["evidence"]["char"] is None
    assert o["evidence"]["why"] == "abstain:out_of_group"
    m = NM.load_method("rr_shape", str(_write_model(tmp_path / "h.json", thr=1e9)))
    o = m.score([rens[1]], "b")[0]
    assert o["evidence"]["why"] == "abstain:low_margin" and o["evidence"]["char"] is None
    assert set(o["sims"]) == {"人", "入", "八"}                       # 分差不够仍给分，弃权记在证据里


def test_calibrate_with_sibling_calib(model_file):
    (model_file.parent / "rr_shape.calib.json").write_text(json.dumps(
        {"format": "near-calib/1", "knots": {"入": [[0.0, 0.5, 1.0], [0.0, 0.5, 1.0]]}, "rule": {"八": 0.99}}),
        encoding="utf-8")
    m = NM.RrShape(model_file)
    outs = m.score([ba(), ru(), _blank()], "b")
    assert m.calibrate(outs[0]["sims"]) == {"八": 0.99}
    p = m.calibrate(outs[1]["sims"])
    assert p["入"] == pytest.approx(outs[1]["sims"]["入"], abs=1e-4) and p["入"] + p["人"] == pytest.approx(1.0)
    assert m.calibrate(outs[2]["sims"]) is None
    # 校准表进方法指纹：换表即换指纹
    fp0 = NM.method_fingerprint("rr_shape", str(model_file))
    (model_file.parent / "rr_shape.calib.json").write_text(json.dumps({"format": "near-calib/1", "rule": {"八": 0.9}}),
                                                           encoding="utf-8")
    assert NM.method_fingerprint("rr_shape", str(model_file)) != fp0
    assert NM.method_fingerprint("rr_shape", str(model_file)).startswith("rr_shape=")


def test_model_dir_form(tmp_path):
    d = tmp_path / "rr_dir"
    d.mkdir()
    _write_model(d / "model.json")
    m = NM.load_method("rr_shape", str(d))
    assert m.score([ba()], "b")[0]["evidence"]["char"] == "八"
    assert m.fingerprint() == NM._dir_fingerprint(d)


# ── 一致性：第四步现役判法 vs 3b 方法 ──────────────────────────────────

def test_same_input_same_score_as_seed_admit_pass(model_file):
    """同一张图、同一个模型：第四步 `_rr_shape_pass` 写进待审格 `evidence.rr_shape` 的结论与分，与 3b 方法的证据逐键相同。"""
    from open_guji_cv.steps.seed_admit_shapes import _rr_shape_pass

    imgs = _probe_imgs()
    keys = [f"p0001c01s{i + 1}" for i in range(len(imgs))]
    ctx = NS(image=lambda kind, key: imgs[keys.index(key)])
    recs = [NS(id=f"b:1:1:{i + 1}", slot=i + 1, sub=None, char="人", admit=False, evidence={}, provenance="match",
               channel="", doubts=[]) for i in range(len(imgs))]
    p = NS(group_flow_rr_shape=str(model_file), patch_missing="error")
    _rr_shape_pass(p, [NS(col=1, chars=recs)], {}, ctx, 1)
    outs = NM.load_method("rr_shape", str(model_file)).score(imgs, "b")
    for r, o, g in zip(recs, outs, imgs):
        assert o["evidence"]["method"] == "rr_shape"
        assert r.evidence["rr_shape"] == {k: v for k, v in o["evidence"].items() if k != "method"}
        v = rr_shape.judge(g, rr_shape.load(str(model_file)))
        assert o["evidence"]["char"] == v["char"] and o["evidence"].get("score") == v.get("score")
        if r.admit:                                                     # 现役放行了：3b 方法给同一个字最高分
            assert r.char == o["evidence"]["char"] == max(o["sims"], key=o["sims"].get)
    assert sum(r.admit for r in recs) == 5                              # 空白格弃权，其余放行


# ── 可选 ctx ───────────────────────────────────────────────────────────

class _Old:
    def score(self, patches, book_id):
        return [{"sims": {"甲": 1.0}, "evidence": {"n": len(patches)}} for _ in patches]


class _New:
    def score(self, patches, book_id, ctx=None, cells=None):
        return [{"sims": {}, "evidence": {"ctx": ctx, "cell": c}} for c in cells]


class _Kw:
    def score(self, patches, book_id, **kw):
        return [{"sims": {}, "evidence": sorted(kw)} for _ in patches]


def test_score_passes_ctx_only_to_methods_that_take_it():
    ps = [np.zeros((4, 4), np.uint8)] * 2
    assert NM.score(_Old(), ps, "b", ctx="C", cells=[1, 2])[0]["evidence"] == {"n": 2}
    assert [o["evidence"] for o in NM.score(_New(), ps, "b", ctx="C", cells=[1, 2])] == [
        {"ctx": "C", "cell": 1}, {"ctx": "C", "cell": 2}]
    assert NM.score(_Kw(), ps, "b", ctx="C", cells=[1, 2])[0]["evidence"] == ["cells", "ctx"]


def test_dir_fingerprint_unchanged_for_dirs(tmp_path):
    """cnn_small 那种模型目录的指纹算法没变（11-27 的写法逐位照抄来比）。"""
    import hashlib
    d = tmp_path / "m"
    d.mkdir()
    (d / "model.json").write_text("{}", encoding="utf-8")
    (d / "fold0.pt").write_bytes(b"\x00\x01")
    h = hashlib.sha256()
    for f in sorted(d.iterdir()):
        h.update(f.name.encode())
        h.update(hashlib.sha256(f.read_bytes()).digest())
    assert NM._dir_fingerprint(d) == h.hexdigest()[:16]
    assert NM._dir_fingerprint(tmp_path / "nope") == "missing"


# ── 书配置 ref ＋ 端到端 ───────────────────────────────────────────────

def test_book_params_without_ref_is_same_object(tmp_path):
    from open_guji_cv.steps.glyph_near import GlyphNearParams, GlyphNearStep
    p = GlyphNearParams(groups={"x": {"chars": ["天", "夭"], "methods": {}}})
    assert GlyphNearStep().book_params(p, make_ctx(tmp_path)) is p


def test_trigger_cands_covers_topk():
    from open_guji_cv.steps.glyph_near import trigger_group
    g = {"rr": {"chars": ["人", "入", "八"], "trigger": "cands"}}
    assert trigger_group([("言", 0.9), ("文", 0.8), ("之", 0.7), ("而", 0.6), ("入", 0.5)], "言", g) == ("rr", "cands")
    assert trigger_group([("言", 0.9), ("文", 0.8), ("之", 0.7), ("而", 0.6), ("也", 0.5), ("入", 0.4)], "言", g) is None
    assert trigger_group([], "八", g) == ("rr", "cands")                              # same 档没有候选，看 char
    assert trigger_group([("言", 0.9), ("入", 0.5)], "言", {"rr": {**g["rr"], "topk": 1}}) is None


def test_glyph_near_rr_shape_end_to_end(tmp_path, model_file):
    from open_guji_cv.steps.glyph_near import GlyphNearParams

    groups = {"rr": {"ref": "rr", "trigger": "cands", "methods": {"rr_shape": str(model_file)}}}
    book = make_book("tbook", params={"glyph_near": {"groups": groups}, "glyph_analyzer": {"enabled": True}})
    ctx = make_ctx(tmp_path, book, raw={1: np.full((400, 300), 255, np.uint8)})
    imgs = {1: ba(), 2: ren(), 3: ru(), 6: _blank()}
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(recs=[
        {"slot": 1, "verdict": "unsure", "candidates": [("人", 0.90), ("八", 0.89)]},
        {"slot": 2, "verdict": "same", "char": "人", "cov": 0.95},
        {"slot": 3, "verdict": "unsure", "candidates": [("言", 0.90), ("文", 0.8), ("之", 0.7), ("入", 0.6)]},  # 首位不在组里
        {"slot": 4, "verdict": "unsure", "candidates": [("八", 0.90)]},             # 字块图读不到
        {"slot": 5, "verdict": "same", "char": "言", "cov": 0.95},
        {"slot": 6, "verdict": "unsure", "candidates": [("人", 0.90)]}]))           # 空白：弃权、无分
    write_product(ctx, "cell_shrink", 1, char_index=page_chars(recs=[
        {"slot": s, "bbox_page": (30.0, 10.0 + 50 * s, 70.0, 50.0 + 50 * s), "patch_key": f"p0001c01s{s}"}
        for s in range(1, 7)]))
    for s, g in imgs.items():
        ctx.cache.put("tbook", "char_patch", f"p0001c01s{s}", g)

    p = ctx.params_for(_glyph_near_step())
    assert p.groups["rr"]["chars"] == ["人", "入", "八"] and "ref" not in p.groups["rr"]    # 按登记表展开
    assert p.methods_sha.startswith("rr:rr_shape=")
    assert p.methods_sha == GlyphNearParams(groups=p.groups).methods_sha

    out = run_steps(ctx, 1, ["glyph_near", "glyph_analyzer"])
    pn = out["glyph_near"]
    sha = rr_shape.fingerprint(str(model_file))                             # 与第四步参数指纹 rs 段同算法
    assert pn.models == {"rr_shape:rr": sha}
    # 4d（cv #1999 `_rr_shape_from_3b`）比的是 methods_sha 里的 `rr_shape=<指纹>`，与它按 group_flow_rr_shape 算的同一份
    assert NM.method_fingerprint("rr_shape", str(model_file)) in {x.split(":", 1)[1] for x in pn.methods_sha.split(";")}
    near = pn.by_id()
    assert list(near) == [f"tbook:1:1:{s}" for s in (1, 2, 3, 4, 6)]
    model = rr_shape.load(str(model_file))
    trail = {}
    for s in (1, 2, 3, 6):
        mo = near[f"tbook:1:1:{s}"].methods[0]
        assert mo.method == "rr_shape:rr" and near[f"tbook:1:1:{s}"].trigger == "cands"
        v = rr_shape.judge(imgs[s], model)
        trail[s] = {"method": "rr_shape", **{k: v[k] for k in ("char", "why", "nn", "score", "geo") if k in v}}
        assert mo.evidence == trail[s]
    assert [trail[s]["char"] for s in (1, 2, 3, 6)] == ["八", "人", "入", None]
    miss = near["tbook:1:1:4"].methods[0]
    assert miss.sims == {} and miss.evidence["error"] == "patch_missing"

    fin = out["glyph_analyzer"].by_id()
    a = fin["tbook:1:1:1"]
    assert a.p_src == "" and all(c.p is None for c in a.cands)              # 没有校准表：只当证据
    assert {c.char: c.evidence["b"]["rr_shape:rr"] for c in a.cands if "b" in c.evidence} == {"八": 1.0, "人": 0.0, "入": 0.0}
    for s in (1, 2, 3, 6):                                                  # 4d 取数处：每格 near.methods[方法名]
        assert fin[f"tbook:1:1:{s}"].near == {"group": "rr", "trigger": "cands",
                                              "methods": {"rr_shape": {**trail[s], "model": sha}}}
    assert fin["tbook:1:1:4"].near["methods"]["rr_shape"]["error"] == "patch_missing"
    assert fin["tbook:1:1:5"].near == {} and "near" not in fin["tbook:1:1:5"].model_dump(mode="json")   # 没触发的格不落盘


def _glyph_near_step():
    from open_guji_cv.core.step import STEPS
    return STEPS["glyph_near"]
