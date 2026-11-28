"""3b `glyph_near` 的 near_knn 方法（形近护栏格书级刻形近邻从第四步搬来，2026-11-28）＋保留伪组 `_guard`／`trigger: guard`。

数据全在测试里造（字块图同 `test_near_knn.py`：未＝方框、末＝十字、一＝横；末未是手工形近表里的一对）。要证明的：
- 3b 出的量（全库近邻＋3a 各字前 k 个距离）经 `near_knn_settle` 用 4d 的候选重判，与现役 `near_knn.judge` 逐键相等，
  各弃权档、并列距离（候选次序定胜负）都覆盖；候选里有 3a 没给距离的字 → None（4d 本地现算）；
- 4d 现役 `_near_knn_pass`（near 段、gap 段）把 `near_knn.judge` 换成「3b 的量＋本地补算」后，每格证据、放行、字逐键不变；
- `trigger: guard` 照现役挑格，伪组 `_guard` 的写法守卫、`methods_sha`、端到端。
"""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace as NS

import numpy as np
import pytest

from open_guji_cv.groups import near_knn, rr_shape
from open_guji_cv.groups import near_methods as NM

from helpers import make_book, make_ctx, page_chars, page_match, run_steps, write_product
from test_near_knn import SH, _canvas, bar, box, cross


def _model_dict(shapes, **kw):
    imgs, lab = [], []
    for ch, fn in shapes:
        for d in SH:
            imgs.append(fn(d))
            lab.append(ch)
    F = np.array([rr_shape.features(g)[0] for g in imgs])
    m = F.mean(0)
    _, _, vt = np.linalg.svd(F - m, full_matrices=False)
    P = vt[:6]
    d = {"schema": near_knn.SCHEMA, "k": 7, "votes_min": 7, "ratio_max": 0.8, "full_votes_min": 4, "min_n": 5,
         "guard": 1e9, "skip_chars": [], "skip_groups": [],
         "pca_mean": near_knn.pack(m), "pca": near_knn.pack(P), "bank": near_knn.pack((F - m) @ P.T), "labels": lab}
    d.update(kw)
    return d


BASE = (("未", box), ("末", cross), ("一", bar))
MODELS = {
    "base": (BASE, {}),
    "loose": (BASE, {"votes_min": 4, "ratio_max": 1.5, "full_votes_min": 3}),     # 票、比放松：放行多、全库不同意也出现
    "guard": (BASE, {"guard": 0.0}),                                              # 全部离库太远
    "tie": (BASE + (("口", box),), {"votes_min": 4, "ratio_max": 1.01}),          # 口 与 未 同图：距离逐个并列
    "few": (BASE + (("丁", lambda d: cross(d)),), {"min_n": 9}),                  # 每字 8 格 < min_n：候选全不够格
}


@pytest.fixture
def models(tmp_path):
    out = {}
    for k, (shapes, kw) in MODELS.items():
        f = tmp_path / f"{k}.json"
        f.write_text(json.dumps(_model_dict(shapes, **kw), ensure_ascii=False), encoding="utf-8")
        out[k] = f
    near_knn.load.cache_clear()
    return out


def _imgs():
    both = np.minimum(box(0), cross(0))
    return [box(-2), box(1), cross(-1), cross(2), bar(0), bar(-3), both, _canvas()]


CANDS = (["未", "末"], ["末", "未"], ["未", "一"], ["末", "一", "未"], ["未", "口"], ["口", "未"], ["口", "末", "一"],
         ["未"], ["未", "鬱"], ["未", "未", "末"], [None, "末", "未"])
CHARS_3A = ("未", "末", "一", "口")                       # 3a 首位＋候选（「整理本字」鬱、丁 不在里面）


# ── 3b 量＋定档 ＝ 现役 judge ──────────────────────────────────────────

def test_settle_equals_judge_every_branch(models):
    seen = set()
    for k, f in models.items():
        model = near_knn.load(str(f))
        for g in _imgs():
            ev = NM.near_knn_measure(rr_shape.features(g)[0], model, CHARS_3A)
            for cands in CANDS:
                want = near_knn.judge(g, model, cands)
                got = NM.near_knn_settle(ev, model, cands)
                assert got == want, (k, cands, got, want)
                assert json.dumps(got, ensure_ascii=False) == json.dumps(want, ensure_ascii=False)   # 键次序也同
                seen.add(want["why"])
                if want.get("pick") and len(want["cands"]) == 2 and "口" in want["cands"] and "未" in want["cands"]:
                    seen.add("tie:" + want["pick"])                                # 并列时候选次序定胜负，两个方向都有
    assert {"agree", "abstain:low_margin", "abstain:full_dissent", "abstain:out_of_book", "abstain:few_cands",
            "abstain:no_ink"} <= seen
    assert {"tie:口", "tie:未"} <= seen


def test_settle_needs_dists_for_every_eligible_cand(models):
    model = near_knn.load(str(models["base"]))
    ev = NM.near_knn_measure(rr_shape.features(box(0))[0], model, ["未", "末"])
    assert set(ev["dists"]) == {"未", "末"} and all(len(v) == 7 for v in ev["dists"].values())
    assert NM.near_knn_settle(ev, model, ["未", "一"]) is None                     # 一 够格但 3a 没给距离：4d 本地现算
    assert NM.near_knn_settle(ev, model, ["未", "鬱"]) == near_knn.judge(box(0), model, ["未", "鬱"])   # 库里没有的字不算
    assert NM.near_knn_settle({"method": "near_knn", "error": "patch_missing"}, model, ["未", "末"]) is None
    assert NM.near_knn_settle({"nan": True, "chars": []}, model, ["未", "末"]) == {"char": None, "why": "abstain:nan"}
    assert NM.near_knn_settle({"nan": True, "chars": []}, model, ["未"]) == {"char": None, "why": "abstain:few_cands"}


# ── 方法：形状、指纹 ──────────────────────────────────────────────────

def test_method_shape_and_fingerprint(models):
    f = models["base"]
    m = NM.load_method("near_knn", str(f))
    assert m.patch == "char_patch" and m.lib
    cells = [{"char": None, "candidates": [("未", 0.9), ("末", 0.8), ("一", 0.7), ("鬱", 0.6)]},
             {"char": "末", "candidates": []}]
    a, b = m.score([box(1), cross(1)], "bk", cells=cells)
    assert a["evidence"]["method"] == "near_knn" and a["evidence"]["chars"] == ["未", "末", "一", "鬱"]
    assert set(a["evidence"]["dists"]) == {"未", "末", "一"}
    assert a["sims"] == {"未": 1.0} and m.calibrate(a["sims"]) is None
    assert b["evidence"]["chars"] == ["末"] and b["sims"] == {}                 # 够格的字不到两个
    fp = near_knn.fingerprint(str(f))                                          # 第四步参数指纹 nk 段同算法
    assert NM.lib_fingerprint(f) == fp == m.model_sha and NM.method_fingerprint("near_knn", str(f)) == f"near_knn={fp}"


# ── 一致性：现役 `_near_knn_pass` 换成「3b 的量＋本地补算」，逐格不变 ──────

def _cells(imgs):
    """(待审格, 3a MatchRec, 整理本字)：护栏、near_form 疑问、字组、gap、整理本字不在 3a 里、库里没有的字、人裁、硬疑问……"""
    spec = [  # (本格字, doubts, evidence, 3a 首位, 3a 候选, 3a 护栏, 3a 判档, 整理本字)
        ("未", [], {"guard": "conflict"}, "未", [("未", .9), ("末", .8)], "conflict", "same", "末"),
        ("末", ["near_form"], {}, None, [("末", .9), ("未", .89)], None, "unsure", "未"),
        ("未", [], {"guard": "never_match"}, "未", [("未", .9)], "never_match", "same", "一"),          # 一 不在 3a 里
        ("一", [], {"group": {"id": "g1"}}, None, [("一", .9), ("末", .8)], None, "unsure", "未"),     # 字组格：3b 不触发
        ("末", [], {}, None, [("末", .9), ("一", .85), ("未", .8)], None, "unsure", "未"),           # gap
        ("未", [], {}, None, [("未", .9), ("末", .85)], None, "unsure", "未"),                       # gap 段：库首位＝整理本，不判
        ("未", ["near_form"], {}, None, [("未", .9), ("鬱", .85)], None, "unsure", "鬱"),            # 鬱 库里没有：候选不足
        ("末", ["solo_confusable"], {}, None, [("末", .9), ("未", .8)], None, "unsure", None),
        ("未", ["occluded", "near_form"], {}, None, [("未", .9), ("末", .8)], None, "unsure", "末"),   # 硬疑问：不碰
        ("末", [], {"guard": "conflict"}, "末", [("末", .9), ("未", .8)], "conflict", "same", "未"),
    ]
    cells, mmap, amap = [], {}, {}
    for i, (ch, ds, ev, mc, cands, guard, verdict, ref) in enumerate(spec):
        cid = f"b:1:1:{i + 1}"
        cells.append(NS(id=cid, slot=i + 1, sub=None, char=ch, admit=False, provenance="match", channel="",
                        doubts=list(ds), evidence=dict(ev)))
        mmap[cid] = NS(id=cid, char=mc, candidates=cands, guard=guard, verdict=verdict)
        if ref:
            amap[cid] = (ref,)
    return cells, mmap, amap


@pytest.mark.parametrize("k", ["base", "loose", "guard", "tie"])
def test_pass_with_3b_quantities_matches_live(models, k, monkeypatch):
    from open_guji_cv.steps.glyph_near import trigger_groups
    from open_guji_cv.steps.seed_admit_shapes import _near_knn_pass

    imgs = [box(1), cross(-1), box(-2), bar(0), cross(2), box(2), box(-1), cross(1), box(0), cross(0)]
    keys = [f"p0001c01s{i + 1}" for i in range(len(imgs))]
    ctx = NS(image=lambda kind, key: imgs[keys.index(key)], book=NS(codepoints=None))
    cells, mmap, amap = _cells(imgs)
    p = NS(group_flow_near_knn=str(models[k]), patch_missing="error", near_knn_gap=True)

    live = copy.deepcopy(cells)
    for stage in ("near", "gap"):
        _near_knn_pass(p, [NS(col=1, chars=live)], amap, mmap, ctx, 1, stage=stage)

    # 3b：按 `trigger: guard` 挑格、出量（3a 首位＋候选的字）
    m = NM.load_method("near_knn", str(models[k]))
    groups = {"_guard": {"trigger": "guard", "gap": True, "methods": {"near_knn": str(models[k])}}}
    by_img, how = {}, {}
    for c, g in zip(cells, imgs):
        r = mmap[c.id]
        t = trigger_groups(r.candidates, r.char, groups, r)
        if t:
            how[c.id] = t[0][1]
            by_img[id(g)] = m.score([g], "b", cells=[{"char": r.char, "candidates": r.candidates}])[0]["evidence"]
    assert how == {"b:1:1:1": "guard", "b:1:1:2": "near_form", "b:1:1:3": "guard", "b:1:1:4": "near_form",
                   "b:1:1:5": "near_form", "b:1:1:6": "near_form", "b:1:1:7": "near_form", "b:1:1:8": "near_form",
                   "b:1:1:9": "near_form", "b:1:1:10": "guard"}             # 未末 是手工形近表的字：3a 里有就 near_form
    by_img.pop(id(imgs[4]))                                                 # 再造一格 3b 没触发的（4d 本地现算）

    # 4d：先查 3b，罩不住（没触发、或候选里有 3a 没给距离的字）本地现算并计数
    orig = near_knn.judge
    n = {"3b": 0, "local": 0}

    def judge_via_3b(img, model, cands):
        ev = by_img.get(id(img))
        v = NM.near_knn_settle(ev, model, cands) if ev is not None else None
        if v is None:
            n["local"] += 1
            return orig(img, model, cands)
        n["3b"] += 1
        return v

    monkeypatch.setattr(near_knn, "judge", judge_via_3b)
    new = copy.deepcopy(cells)
    for stage in ("near", "gap"):
        _near_knn_pass(p, [NS(col=1, chars=new)], amap, mmap, ctx, 1, stage=stage)
    for a, b in zip(live, new):
        assert (a.char, a.admit, a.channel, a.provenance, a.doubts) == (b.char, b.admit, b.channel, b.provenance, b.doubts)
        assert json.dumps(a.evidence, ensure_ascii=False) == json.dumps(b.evidence, ensure_ascii=False)
    assert n["3b"] >= 4 and n["local"] >= 2                                    # 两路都走到（字组格、整理本字 一 不在 3a 里）
    assert sum("near_knn" in c.evidence for c in live) >= 6
    if k in ("base", "loose"):
        assert any(c.channel == "near_knn" for c in live)


# ── 触发与伪组守卫 ────────────────────────────────────────────────────

def test_guard_trigger_rules():
    from open_guji_cv.steps.glyph_near import GlyphNearParams, trigger_groups

    g = {"_guard": {"trigger": "guard", "methods": {}}}
    rec = NS(guard="never_match", verdict="same")
    assert trigger_groups([("言", .9)], "言", g, rec) == [("_guard", "guard")]
    assert trigger_groups([("言", .9), ("文", .8), ("未", .7)], None, g, NS(guard=None, verdict="unsure")) == [("_guard", "near_form")]
    assert trigger_groups([("言", .9), ("文", .8), ("天", .7), ("未", .6)], None, g, NS(guard=None, verdict="unsure")) == []
    assert trigger_groups([("言", .9)], "末", g, NS(guard=None, verdict="same")) == [("_guard", "near_form")]
    assert trigger_groups([("言", .9)], None, g, NS(guard=None, verdict="unsure")) == []           # 没开 gap
    g2 = {"_guard": {"trigger": "guard", "gap": True, "methods": {}}}
    assert trigger_groups([("言", .9)], None, g2, NS(guard=None, verdict="unsure")) == [("_guard", "gap")]
    assert trigger_groups([("言", .9)], "言", g2, NS(guard=None, verdict="same")) == []
    with pytest.raises(ValueError, match="_guard"):
        GlyphNearParams(groups={"x": {"chars": ["未"], "trigger": "guard", "methods": {}}})
    with pytest.raises(ValueError, match="_guard"):
        GlyphNearParams(groups={"_guard": {"trigger": "cands", "methods": {}}})
    with pytest.raises(ValueError, match="_guard"):
        GlyphNearParams(groups={"_guard": {"trigger": "guard", "ref": "men", "methods": {}}})
    from open_guji_cv.groups.near_registry import expand_refs
    with pytest.raises(ValueError, match="保留伪组"):
        expand_refs({"_guard": {"ref": "men"}})


# ── 端到端 ─────────────────────────────────────────────────────────────

def _glyph_near_step():
    from open_guji_cv.core.step import STEPS
    return STEPS["glyph_near"]


def test_glyph_near_near_knn_end_to_end(tmp_path, models):
    from open_guji_cv.steps.glyph_near import GlyphNearParams

    mf = models["base"]
    groups = {"_guard": {"trigger": "guard", "gap": True, "methods": {"near_knn": str(mf)}},
              "t": {"ref": "rr", "trigger": "cands", "methods": {}}}            # 登记表组与伪组同在：ref 照展开
    book = make_book("tbook", params={"glyph_near": {"groups": groups}, "glyph_analyzer": {"enabled": True}})
    ctx = make_ctx(tmp_path, book, raw={1: np.full((400, 300), 255, np.uint8)})
    imgs = {1: box(1), 2: cross(1), 3: bar(0), 6: _canvas()}
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(recs=[
        {"slot": 1, "verdict": "same", "char": "未", "cov": 0.95, "guard": "conflict", "candidates": [("未", .95), ("末", .9)]},
        {"slot": 2, "verdict": "unsure", "candidates": [("言", 0.90), ("末", 0.8), ("一", 0.7)]},    # near_form（第三名）
        {"slot": 3, "verdict": "unsure", "candidates": [("一", 0.90), ("十", 0.8)]},                 # gap
        {"slot": 4, "verdict": "unsure", "candidates": [("未", 0.90)]},                             # 字块图读不到
        {"slot": 5, "verdict": "same", "char": "言", "cov": 0.95},                                  # 不触发
        {"slot": 6, "verdict": "unsure", "candidates": [("末", 0.90), ("未", 0.8)]}]))              # 空白：无墨
    write_product(ctx, "cell_shrink", 1, char_index=page_chars(recs=[
        {"slot": s, "bbox_page": (30.0, 10.0 + 50 * s, 70.0, 50.0 + 50 * s), "patch_key": f"p0001c01s{s}"}
        for s in range(1, 7)]))
    for s, g in imgs.items():
        ctx.cache.put("tbook", "char_patch", f"p0001c01s{s}", g)

    p = ctx.params_for(_glyph_near_step())
    fp = near_knn.fingerprint(str(mf))
    assert p.groups["_guard"] == groups["_guard"] and p.groups["t"]["chars"] == ["人", "入", "八"]
    assert p.methods_sha == f"_guard:near_knn={fp}" == GlyphNearParams(groups=p.groups).methods_sha

    out = run_steps(ctx, 1, ["glyph_near", "glyph_analyzer"])
    pn = out["glyph_near"]
    assert pn.models == {"near_knn:_guard": fp}
    trig = {cid: r.trigger for cid, r in pn.by_id().items()}
    assert trig == {"tbook:1:1:1": "guard", "tbook:1:1:2": "near_form", "tbook:1:1:3": "gap",
                    "tbook:1:1:4": "near_form", "tbook:1:1:6": "near_form"}
    model = near_knn.load(str(mf))
    ev1 = pn.get("tbook:1:1:1", "_guard").methods[0].evidence
    assert ev1["chars"] == ["未", "末"] and pn.get("tbook:1:1:1", "t") is None
    for s, cands in ((1, ["未", "末"]), (2, ["末", "一"]), (3, ["一", "未"]), (6, ["末", "未"])):
        ev = pn.get(f"tbook:1:1:{s}", "_guard").methods[0].evidence
        got = NM.near_knn_settle(ev, model, cands)
        want = near_knn.judge(imgs[s], model, cands)
        if s == 3:
            assert got is None                                              # 未 不在 3a 里：4d 本地现算
        else:
            assert got == want
    assert NM.near_knn_settle(ev1, model, ["未", "末"])["char"] == "未"
    assert pn.get("tbook:1:1:6", "_guard").methods[0].evidence == {"method": "near_knn", "char": None, "why": "abstain:no_ink"}
    assert pn.get("tbook:1:1:4", "_guard").methods[0].evidence["error"] == "patch_missing"

    fin = out["glyph_analyzer"].by_id()
    a = fin["tbook:1:1:1"]
    assert a.p_src == "" and all(c.p is None for c in a.cands)
    assert a.near["_guard"]["trigger"] == "guard"
    assert a.near["_guard"]["methods"]["near_knn"] == {**ev1, "model": fp}
    assert fin["tbook:1:1:5"].near == {}
