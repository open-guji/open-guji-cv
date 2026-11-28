"""3b `glyph_near` 的 book_knn 方法（字组书级刻形近邻从第四步搬来，拆成前段＋定档，2026-11-28）。

数据全在测试里造（字块图同 `test_book_knn.py`：口＝方框、十＝十字、一＝横、背景刻例 `~`）。要证明的：
- 拆后「前段 `book_knn_measure`＋定档 `book_knn_settle`」与现役 `book_knn.judge(图, 模型, ref)` 整体逐键相等，A、B、各弃权档都覆盖；
- 同一张图、同一份库，第四步 `_book_knn_pass` 写的 `evidence.book_knn` ＝ 4d 拿 3b 证据定档的结果；
- `lib_fingerprint` 与第四步参数指纹 `bk` 段同值，进 `methods_sha`。
"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import cv2
import numpy as np
import pytest

from open_guji_cv.groups import book_knn, rr_shape
from open_guji_cv.groups import near_methods as NM

from helpers import make_book, make_ctx, page_chars, page_match, run_steps, write_product
from test_book_knn import box, cross


def _canvas():
    return np.full((120, 120), 255, np.uint8)


def bar(dx=0):
    g = _canvas()
    cv2.line(g, (15 + dx, 60), (105 + dx, 60), 0, 9)
    return g


def _model_dict(labels="口口口口口十十十十十", extra=(), **kw):
    """库：口、十 各 5 格（± 位移）；`extra` 另加 (标签, 图)。数组写成列表（同 `book_knn_train.py` 导出的 JSON）。"""
    imgs = [box(d) for d in (-4, -2, 0, 2, 4)] + [cross(d) for d in (-4, -2, 0, 2, 4)] + [g for _, g in extra]
    lab = list(labels) + [c for c, _ in extra]
    F = np.array([rr_shape.features(g)[0] for g in imgs])
    m = F.mean(0)
    _, _, vt = np.linalg.svd(F - m, full_matrices=False)
    P = vt[:4]
    d = {"schema": book_knn.SCHEMA, "group": "t", "pca_mean": m.tolist(), "pca": P.tolist(),
         "bank": ((F - m) @ P.T).tolist(), "labels": lab, "k": 5, "votes_min": 5, "ratio_max": 0.8,
         "ref_votes_min": 4, "ref_ratio_max": 1.0, "guard": 1e9}
    d.update(kw)
    return d


MODELS = {
    "base": {},                                             # A 档为主
    "b_only": {"votes_min": 99},                            # A 档关掉：只剩 B 档（要整理本同字）
    "b_tight": {"votes_min": 99, "ref_ratio_max": 0.3},     # B 档距离比也收紧：多数 low_margin 且 b_ok 假
    "guard": {"guard": 0.0},                                # 全部组外字弃权
}


@pytest.fixture
def models(tmp_path):
    d = tmp_path / "groups" / "book_knn"
    d.mkdir(parents=True)
    out = {}
    for k, kw in MODELS.items():
        f = d / f"{k}.json"
        f.write_text(json.dumps(_model_dict(**kw), ensure_ascii=False), encoding="utf-8")
        out[k] = f
    f = d / "bg.json"                                       # 十 换成背景刻例：近邻投 `~` → 弃权
    f.write_text(json.dumps(_model_dict(labels="口口口口口~~~~~"), ensure_ascii=False), encoding="utf-8")
    out["bg"] = f
    f = d / "mix.json"                                      # 口 2 格、十 3 格、一 5 格：票数、距离比各档都有
    f.write_text(json.dumps(_model_dict(labels="口口十十十十十口口口", extra=[("一", bar(d_)) for d_ in (-4, -2, 0, 2, 4)],
                                        votes_min=4, ratio_max=0.9, ref_votes_min=3, ref_ratio_max=1.2),
                            ensure_ascii=False), encoding="utf-8")
    out["mix"] = f
    book_knn.load.cache_clear()
    return out


def _imgs():
    """口、十、一 各几种位移，空白（无墨），一个口十叠在一起的怪字。"""
    both = np.minimum(box(0), cross(0))
    return ([box(d) for d in (-3, 1, 3)] + [cross(d) for d in (-3, 1, 3)] + [bar(d) for d in (-3, 0, 3)]
            + [_canvas(), both])


REFS = (None, "口", "十", "一", book_knn.BACKGROUND, "閒")


# ── 拆分：前段＋定档 ＝ 现役 judge ─────────────────────────────────────

def test_split_equals_judge_every_tier(models):
    """各库 × 各图 × 各整理本字：`book_knn_settle(book_knn_measure(f), ref)` 与 `book_knn.judge(图, 模型, ref)` 逐键相等
    （同值、同舍入、同键次序），A、B、各弃权档都出现过。"""
    seen = set()
    for k, f in models.items():
        model = book_knn.load(str(f))
        for g in _imgs():
            front = NM.book_knn_measure(rr_shape.features(g)[0], model)
            assert front == book_knn.judge(g, model, None) | ({"b_ok": front["b_ok"]} if "b_ok" in front else {})
            assert ("b_ok" in front) == (front["why"] == "abstain:low_margin")
            for ref in REFS:
                want = book_knn.judge(g, model, ref)
                got = NM.book_knn_settle(front, ref)
                assert got == want and list(got) == [x for x in NM.BOOK_KNN_KEYS if x in want], (k, ref, front, want)
                assert json.dumps(got, ensure_ascii=False) == json.dumps(
                    {x: want[x] for x in NM.BOOK_KNN_KEYS if x in want}, ensure_ascii=False)   # 第四步 trail 的字节
                seen.add(want["tier"] or want["why"])
                if front.get("b_ok") is False and ref == front["pick"]:
                    seen.add("ref_hit_b_fail")                     # 整理本字＝pick 但 B 档门槛不过：仍弃权
    assert {"A", "B", "abstain:low_margin", "abstain:no_ink", "abstain:out_of_group", "abstain:background",
            "ref_hit_b_fail"} <= seen


def test_settle_ignores_method_and_b_ok_keys():
    ev = {"method": "book_knn", "pick": "口", "votes": 4, "ratio": 0.9, "nn": 1.0, "char": None,
          "why": "abstain:low_margin", "tier": None, "b_ok": True}
    assert NM.book_knn_settle(ev, "口") == {"char": "口", "why": "agree_ref", "tier": "B", "pick": "口", "votes": 4,
                                            "ratio": 0.9, "nn": 1.0}
    assert NM.book_knn_settle(ev, "十") == {k: ev[k] for k in NM.BOOK_KNN_KEYS}
    assert NM.book_knn_settle({**ev, "b_ok": False}, "口")["char"] is None
    a = {**ev, "why": "agree", "char": "口", "tier": "A"}
    a.pop("b_ok")
    assert NM.book_knn_settle(a, "十") == {k: a[k] for k in NM.BOOK_KNN_KEYS}           # A 档不看整理本
    assert NM.book_knn_settle({"method": "book_knn", "char": None, "why": "abstain:no_ink", "tier": None}, "口") == \
        {"char": None, "why": "abstain:no_ink", "tier": None}


# ── 方法：形状、指纹 ──────────────────────────────────────────────────

def test_method_shape_and_fingerprint(models):
    f = models["base"]
    m = NM.load_method("book_knn", str(f))
    assert m.patch == "char_patch" and m.lib
    outs = m.score(_imgs(), "anybook")
    model = book_knn.load(str(f))
    for g, o in zip(_imgs(), outs):
        ev = o["evidence"]
        assert ev["method"] == "book_knn"
        assert NM.book_knn_settle(ev, None) == book_knn.judge(g, model, None)
        if "pick" in ev:
            assert o["sims"] == {ev["pick"]: round(ev["votes"] / 5, 4)}
        else:
            assert o["sims"] == {}
        assert m.calibrate(o["sims"]) is None
    fp = book_knn.fingerprint(str(f))                                       # 第四步参数指纹 bk 段同算法
    assert NM.lib_fingerprint(str(f)) == NM.lib_fingerprint(f) == fp == m.fingerprint() == m.model_sha
    assert NM.method_fingerprint("book_knn", str(f)) == f"book_knn={fp}"
    assert NM.lib_fingerprint(f.parent / "nope.json") == "" == book_knn.fingerprint(str(f.parent / "nope.json"))
    d = f.parent / "dirform"
    d.mkdir()
    (d / "model.json").write_bytes(f.read_bytes())
    assert NM.lib_fingerprint(d) == fp and NM.load_method("book_knn", str(d)).model_sha == fp


def test_background_pick_gives_no_sims(models):
    m = NM.load_method("book_knn", str(models["bg"]))
    o = m.score([cross(1)], "b")[0]
    assert o["evidence"]["why"] == "abstain:background" and o["sims"] == {}


# ── 一致性：第四步现役 `_book_knn_pass` vs 3b 证据＋定档 ────────────────

@pytest.mark.parametrize("k", ["base", "b_only", "b_tight", "bg", "mix"])
def test_same_input_same_evidence_as_seed_admit_pass(models, k):
    """同一张图、同一份库、同一个整理本字：`_book_knn_pass` 给待审组格写的 `evidence.book_knn` ＝ `book_knn_settle(3b 证据, ref)`，
    放行与否、放行字也由它定。整理本字各格轮着换（含无整理本）。"""
    from open_guji_cv.steps.seed_admit_shapes import _book_knn_pass

    imgs = _imgs()
    keys = [f"p0001c01s{i + 1}" for i in range(len(imgs))]
    ctx = NS(image=lambda kind, key: imgs[keys.index(key)])
    cells = [NS(id=f"b:1:1:{i + 1}", slot=i + 1, sub=None, char="口", admit=False, provenance="match", channel="",
                doubts=["near_form"], evidence={"group": {"id": "t"}}) for i in range(len(imgs))]
    refs = {c.id: REFS[i % len(REFS)] for i, c in enumerate(cells)}
    amap = {cid: (ref,) for cid, ref in refs.items() if ref is not None}
    p = NS(group_flow_book_knn={"t": str(models[k])}, patch_missing="error")
    _book_knn_pass(p, [NS(col=1, chars=cells)], amap, ctx, 1)
    outs = NM.load_method("book_knn", str(models[k])).score(imgs, "b")
    n_admit = 0
    for c, o in zip(cells, outs):
        want = NM.book_knn_settle(o["evidence"], refs[c.id])
        assert c.evidence["book_knn"] == want
        assert json.dumps(c.evidence["book_knn"], ensure_ascii=False) == json.dumps(want, ensure_ascii=False)
        assert c.admit == (want["char"] is not None)
        if c.admit:
            n_admit += 1
            assert c.char == want["char"] and c.channel == "book_knn"
    if k in ("base", "mix"):
        assert n_admit


# ── 端到端 ─────────────────────────────────────────────────────────────

def _glyph_near_step():
    from open_guji_cv.core.step import STEPS
    return STEPS["glyph_near"]


def test_glyph_near_book_knn_end_to_end(tmp_path, models):
    from open_guji_cv.steps.glyph_near import GlyphNearParams

    mf = models["b_only"]
    groups = {"t": {"chars": ["口", "十"], "trigger": "cands", "methods": {"book_knn": str(mf)}}}
    book = make_book("tbook", params={"glyph_near": {"groups": groups}, "glyph_analyzer": {"enabled": True}})
    ctx = make_ctx(tmp_path, book, raw={1: np.full((400, 300), 255, np.uint8)})
    imgs = {1: box(1), 2: cross(1), 3: box(-3), 6: _canvas()}
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(recs=[
        {"slot": 1, "verdict": "unsure", "candidates": [("口", 0.90), ("日", 0.89)]},
        {"slot": 2, "verdict": "same", "char": "十", "cov": 0.95},
        {"slot": 3, "verdict": "unsure", "candidates": [("日", 0.90), ("曰", 0.8), ("口", 0.7)]},   # 首位不在组里：3b 也跑
        {"slot": 4, "verdict": "unsure", "candidates": [("口", 0.90)]},             # 字块图读不到
        {"slot": 5, "verdict": "same", "char": "言", "cov": 0.95},                  # 不触发
        {"slot": 6, "verdict": "unsure", "candidates": [("十", 0.90)]}]))           # 空白：弃权、无分
    write_product(ctx, "cell_shrink", 1, char_index=page_chars(recs=[
        {"slot": s, "bbox_page": (30.0, 10.0 + 50 * s, 70.0, 50.0 + 50 * s), "patch_key": f"p0001c01s{s}"}
        for s in range(1, 7)]))
    for s, g in imgs.items():
        ctx.cache.put("tbook", "char_patch", f"p0001c01s{s}", g)

    p = ctx.params_for(_glyph_near_step())
    fp = book_knn.fingerprint(str(mf))
    assert p.methods_sha == f"t:book_knn={fp}" == "t:" + NM.method_fingerprint("book_knn", str(mf))
    assert p.methods_sha == GlyphNearParams(groups=p.groups).methods_sha

    out = run_steps(ctx, 1, ["glyph_near", "glyph_analyzer"])
    pn = out["glyph_near"]
    assert pn.models == {"book_knn:t": fp}
    near = {k: v[0] for k, v in pn.by_id_all().items()}
    assert list(near) == [f"tbook:1:1:{s}" for s in (1, 2, 3, 4, 6)]
    model = book_knn.load(str(mf))
    for s in (1, 2, 3, 6):
        mo = pn.get(f"tbook:1:1:{s}", "t").methods[0]
        assert mo.method == "book_knn:t" and near[f"tbook:1:1:{s}"].trigger == "cands"
        for ref in REFS:                                                   # 4d 定档 ＝ 现役 judge
            assert NM.book_knn_settle(mo.evidence, ref) == book_knn.judge(imgs[s], model, ref)
    ev1 = near["tbook:1:1:1"].methods[0].evidence
    assert ev1["why"] == "abstain:low_margin" and ev1["b_ok"] is True          # A 档关着：前段只到 low_margin
    assert NM.book_knn_settle(ev1, "口")["tier"] == "B" and NM.book_knn_settle(ev1, None)["char"] is None
    assert near["tbook:1:1:6"].methods[0].sims == {}
    miss = near["tbook:1:1:4"].methods[0]
    assert miss.sims == {} and miss.evidence["error"] == "patch_missing"

    fin = out["glyph_analyzer"].by_id()
    a = fin["tbook:1:1:1"]
    assert a.p_src == "" and all(c.p is None for c in a.cands)              # 没有校准表：只当证据
    m1 = fin["tbook:1:1:1"].near["t"]["methods"]["book_knn"]
    assert m1 == {**ev1, "model": fp}
    assert fin["tbook:1:1:5"].near == {}
