"""第四步 4d 接 3b：`_rr_shape_pass` 开 `group_flow_near_from_3b` 时先读 3b `glyph_near` 的 `rr_shape` 原样结论（CV4 2026-11-28）。

数据全在测试里造（字块图、模型同 `test_glyph_near_rr_shape.py`）。要点：读 3b 与本地现算逐格同一结论；
3b 没有的格、备选切法列本地现算；模型不是同一份报错；开关关着不碰 3b 产物。
"""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace as NS

import pytest

from open_guji_cv.groups import near_methods as NM
from open_guji_cv.products.kinds.read import ColumnNear, NearMethodOut, NearRec, PageNear
from open_guji_cv.steps.seed_admit_shapes import _rr_shape_pass

from test_glyph_near_rr_shape import _probe_imgs, _write_model, model_file  # noqa: F401
from test_glyph_near_hou_shape import models  # noqa: F401
from test_glyph_near_part_shape import model as part_model  # noqa: F401
from test_glyph_near_pair_shape import models as pair_models  # noqa: F401
from test_glyph_near_book_knn import models as bk_models  # noqa: F401
from test_glyph_near_near_knn import models as nk_models  # noqa: F401
from test_glyph_near_stroke_veto import models as sv_models  # noqa: F401


def _recs(n):
    return [NS(id=f"b:1:1:{i + 1}", slot=i + 1, sub=None, char="人", admit=False, evidence={}, provenance="match",
               channel="", doubts=[]) for i in range(n)]


def _near(model, imgs, recs, covered, sha=None):
    outs = NM.load_method("rr_shape", str(model)).score(imgs, "b")
    chars = [NearRec(id=r.id, slot=r.slot, group="rr", trigger="member",
                     methods=[NearMethodOut(method="rr_shape:rr", sims=o["sims"], evidence=o["evidence"])])
             for i, (r, o) in enumerate(zip(recs, outs)) if i in covered]
    if sha is None:
        sha = "rr:" + NM.method_fingerprint("rr_shape", str(model))
    return PageNear(page=1, methods_sha=sha, columns=[ColumnNear(col=1, chars=chars)])


class _Ctx:
    def __init__(self, imgs, near, allow, alt=frozenset()):
        self.imgs, self.near, self.allow, self.alt, self.logs = imgs, near, allow, alt, []
        self.keys = [f"p0001c01s{i + 1}" for i in range(len(imgs))]

    def image(self, kind, key):
        i = self.keys.index(key)
        assert i in self.allow, f"{key} 应读 3b，不该本地读图"
        return self.imgs[i]

    def product(self, kind, page):
        assert kind == "glyph_near"
        if self.near is None:
            raise AssertionError("开关关着不该读 3b 产物")
        return self.near

    def alt_cols(self, page):
        return self.alt

    def log(self, msg):
        self.logs.append(msg)


def _run(model, ctx, on):
    recs = _recs(len(ctx.imgs))
    p = NS(group_flow_rr_shape=str(model), patch_missing="error", group_flow_near_from_3b=["rr_shape"] if on else [])
    d = _rr_shape_pass(p, [NS(col=1, chars=recs)], {}, ctx, 1)
    return d, [(r.char, r.admit, r.channel, copy.deepcopy(r.evidence)) for r in recs]


def test_read_3b_same_as_local(model_file):  # noqa: F811
    imgs = _probe_imgs()
    n = len(imgs)
    base = _run(model_file, _Ctx(imgs, None, set(range(n))), False)
    covered = {0, 1, 2, 5}
    ctx = _Ctx(imgs, _near(model_file, imgs, _recs(n), covered), set(range(n)) - covered)
    assert _run(model_file, ctx, True) == base
    assert "读 3b 4" in ctx.logs[0] and "3b 没触发 2" in ctx.logs[0]


def test_alt_column_falls_back_to_local(model_file):  # noqa: F811
    imgs = _probe_imgs()
    n = len(imgs)
    base = _run(model_file, _Ctx(imgs, None, set(range(n))), False)
    ctx = _Ctx(imgs, _near(model_file, imgs, _recs(n), set(range(n))), set(range(n)), alt=frozenset({1}))
    assert _run(model_file, ctx, True) == base
    assert "读 3b 0" in ctx.logs[0] and f"备选切法列 {n}" in ctx.logs[0]


def test_error_cells_fall_back(model_file):  # noqa: F811
    imgs = _probe_imgs()
    n = len(imgs)
    base = _run(model_file, _Ctx(imgs, None, set(range(n))), False)
    near = _near(model_file, imgs, _recs(n), set(range(n)))
    near.columns[0].chars[0].methods[0].evidence = {"error": "patch_missing"}
    assert _run(model_file, _Ctx(imgs, near, {0}), True) == base


def test_model_mismatch_raises(model_file):  # noqa: F811
    imgs = _probe_imgs()
    near = _near(model_file, imgs, _recs(len(imgs)), {0}, sha="rr:rr_shape=0000000000000000")
    with pytest.raises(ValueError, match="不是同一份"):
        _run(model_file, _Ctx(imgs, near, set(range(len(imgs)))), True)


def test_flag_off_does_not_read_3b(model_file):  # noqa: F811
    imgs = _probe_imgs()
    _run(model_file, _Ctx(imgs, None, set(range(len(imgs)))), False)


def test_flag_off_not_in_param_dump():
    from open_guji_cv.steps.seed_admit_params import SeedAdmitParams
    assert "group_flow_near_from_3b" not in SeedAdmitParams(db_path="x").model_dump()
    assert SeedAdmitParams(db_path="x", group_flow_near_from_3b=["rr_shape"]).model_dump()["group_flow_near_from_3b"] == ["rr_shape"]


# ── wu_shape（嗚鳴，CV3 #2006）：证据是 judge() 整个 dict（3b 多一个 method 键，4d 去掉）──────────

def test_wu_shape_read_3b_same_as_local(tmp_path):
    from open_guji_cv.steps.seed_admit_shapes import _wu_shape_pass
    from test_glyph_near_wu_shape import _imgs as _wu_imgs
    from test_wu_shape import _model_file

    model = _model_file(tmp_path, bias=8.0, name="wu_shape.json")[0]
    imgs = _wu_imgs()
    n = len(imgs)

    def recs():
        return [NS(id=f"b:1:1:{i + 1}", slot=i + 1, sub=None, char="嗚", admit=False, evidence={},
                   provenance="match", channel="", doubts=[]) for i in range(n)]

    def run(ctx, on):
        rs = recs()
        p = NS(group_flow_wu_shape=str(model), patch_missing="error",
               group_flow_near_from_3b=["wu_shape"] if on else [])
        d = _wu_shape_pass(p, [NS(col=1, chars=rs)], {}, ctx, 1)
        return d, [(r.char, r.admit, r.channel, copy.deepcopy(r.evidence)) for r in rs]

    base = run(_Ctx(imgs, None, set(range(n))), False)
    outs = NM.load_method("wu_shape", str(model)).score(imgs, "b")
    covered = {0, 2}
    chars = [NearRec(id=r.id, slot=r.slot, group="wu", trigger="cands",
                     methods=[NearMethodOut(method="wu_shape:wu", sims=o["sims"], evidence=o["evidence"])])
             for i, (r, o) in enumerate(zip(recs(), outs)) if i in covered]
    near = PageNear(page=1, methods_sha="wu:" + NM.method_fingerprint("wu_shape", str(model)),
                    columns=[ColumnNear(col=1, chars=chars)])
    assert all("method" in c.methods[0].evidence for c in chars)
    ctx = _Ctx(imgs, near, set(range(n)) - covered)
    assert run(ctx, True) == base
    assert "wu_shape 判法结果 读 3b 2" in ctx.logs[0] and "3b 没触发 1" in ctx.logs[0]


# ── hou_shape（候𠋫，CV3 #2007）：只改已放行格的字；主遍与晚跑遍读同一条 3b 结论 ──────────

@pytest.mark.parametrize("late", [False, True])
@pytest.mark.parametrize("k", ["geo", "hou", "alt", "mid"])
def test_hou_shape_read_3b_same_as_local(models, k, late):
    from open_guji_cv.steps.seed_admit_shapes import _hou_shape_pass
    from test_glyph_near_hou_shape import _imgs as _hou_imgs

    model = models[k]
    imgs = _hou_imgs()
    n = len(imgs)

    def recs():
        return [NS(id=f"b:1:1:{i + 1}", slot=i + 1, sub=None, char="𠋫", admit=True, evidence={},
                   provenance="match", channel="match_ref", doubts=[]) for i in range(n)]

    def run(ctx, on):
        rs = recs()
        p = NS(group_flow_hou_shape=str(model), patch_missing="error",
               group_flow_near_from_3b=["hou_shape"] if on else [])
        _hou_shape_pass(p, [NS(col=1, chars=rs)], ctx, 1, only_unjudged=late)
        return [(r.char, r.admit, r.channel, copy.deepcopy(r.evidence)) for r in rs]

    base = run(_Ctx(imgs, None, set(range(n))), False)
    outs = NM.load_method("hou_shape", str(model)).score(imgs, "b")
    covered = set(range(0, n, 2))
    chars = [NearRec(id=r.id, slot=r.slot, group="hou", trigger="cands",
                     methods=[NearMethodOut(method="hou_shape:hou", sims=o["sims"], evidence=o["evidence"])])
             for i, (r, o) in enumerate(zip(recs(), outs)) if i in covered]
    near = PageNear(page=1, methods_sha="hou:" + NM.method_fingerprint("hou_shape", str(model)),
                    columns=[ColumnNear(col=1, chars=chars)])
    ctx = _Ctx(imgs, near, set(range(n)) - covered)
    assert run(ctx, True) == base
    assert f"hou_shape 判法结果 读 3b {len(covered)}" in ctx.logs[0]


# ── part_shape（一个模型挂多对，CV3 #2011）：按 (格 id, 对) 取，指纹按 {path, pair} 逐对比 ──────────

@pytest.mark.parametrize("k", ["ci", "shu", "zan", "rnd"])
@pytest.mark.parametrize("admitted", [False, True])
def test_part_shape_read_3b_same_as_local(part_model, k, admitted):  # noqa: F811
    from open_guji_cv.steps.seed_admit_shapes import _part_shape_pass
    from test_glyph_near_part_shape import PAIRS, _imgs as _part_imgs

    a, b = PAIRS[k]
    imgs = _part_imgs()
    n = len(imgs)

    def recs():
        return [NS(id=f"b:1:1:{i + 1}", slot=i + 1, sub=None, char=a, admit=admitted, evidence={},
                   provenance="match", channel="match_ref" if admitted else "", doubts=[]) for i in range(n)]

    def run(ctx, on):
        rs = recs()
        p = NS(group_flow_part_shape=str(part_model), patch_missing="error",
               group_flow_near_from_3b=["part_shape"] if on else [])
        d = _part_shape_pass(p, [NS(col=1, chars=rs)], {}, ctx, 1)
        return d, [(r.char, r.admit, r.channel, copy.deepcopy(r.evidence)) for r in rs]

    base = run(_Ctx(imgs, None, set(range(n))), False)
    spec = {"path": str(part_model), "pair": [a, b]}
    outs = NM.load_method("part_shape", spec).score(imgs, "b")
    covered = {0, 2}
    chars = [NearRec(id=r.id, slot=r.slot, group=k, trigger="cands",
                     methods=[NearMethodOut(method=f"part_shape:{k}", sims=o["sims"], evidence=o["evidence"])])
             for i, (r, o) in enumerate(zip(recs(), outs)) if i in covered]
    near = PageNear(page=1, methods_sha=f"{k}:" + NM.method_fingerprint("part_shape", spec),
                    columns=[ColumnNear(col=1, chars=chars)])
    ctx = _Ctx(imgs, near, set(range(n)) - covered)
    assert run(ctx, True) == base
    assert "part_shape 判法结果 读 3b 2" in ctx.logs[0]
    # 换一对的指纹（模型文件同、对不同）→ 报错
    bad = PageNear(page=1, methods_sha=f"{k}:" + NM.method_fingerprint("part_shape", str(part_model)),
                   columns=[ColumnNear(col=1, chars=chars)])
    with pytest.raises(ValueError, match="不是同一份"):
        run(_Ctx(imgs, bad, set(range(n))), True)


# ── pair_shape（每对一个组、证据不带对，CV3 #2015）：按 (格 id, 本组模型指纹) 取；待审补放与 veto 两处都读 ──────

@pytest.mark.parametrize("k", ["zy", "zy_guard", "dt", "dt_multi"])
@pytest.mark.parametrize("which", [0, 1])
def test_pair_shape_read_3b_same_as_local(pair_models, k, which):  # noqa: F811
    from open_guji_cv.steps.seed_admit_shapes import _pair_shape_pass
    from test_glyph_near_pair_shape import CHARS, IMGS

    a, b = CHARS[k]
    ch = (a, b)[which]
    imgs = IMGS[k]()
    n = len(imgs)

    def recs():
        return [NS(id=f"b:1:1:{i + 1}", slot=i + 1, sub=None, char=ch, admit=False, evidence={}, provenance="match",
                   channel="", doubts=[]) for i in range(n)]

    def run(ctx, on):
        rs = recs()
        p = NS(group_flow_pair_shape=str(pair_models[k]), patch_missing="error",
               group_flow_near_from_3b=["pair_shape"] if on else [])
        d = _pair_shape_pass(p, [NS(col=1, chars=rs)], {r.id: (ch,) for r in rs}, ctx, 1)
        return d, [(r.char, r.admit, r.channel, copy.deepcopy(r.evidence)) for r in rs]

    base = run(_Ctx(imgs, None, set(range(n))), False)
    spec = {"path": str(pair_models[k]), "pair": [a, b]}
    outs = NM.load_method("pair_shape", spec).score(imgs, "b")
    covered = {0, n - 1}
    chars = [NearRec(id=r.id, slot=r.slot, group="g", trigger="cands",
                     methods=[NearMethodOut(method="pair_shape:g", sims=o["sims"], evidence=o["evidence"])])
             for i, (r, o) in enumerate(zip(recs(), outs)) if i in covered]
    # 同页另有一组别的模型（指纹不同）：不该被取到
    sha = "g:" + NM.method_fingerprint("pair_shape", spec) + ";h:pair_shape=0000000000000000"
    near = PageNear(page=1, methods_sha=sha, columns=[ColumnNear(col=1, chars=chars)])
    ctx = _Ctx(imgs, near, set(range(n)) - covered)
    assert run(ctx, True) == base
    assert "pair_shape 判法结果 读 3b 2" in ctx.logs[0]
    # 3b 的模型不是这一份：一条也取不到，全部本地现算，结果照旧
    other = PageNear(page=1, methods_sha="g:pair_shape=0000000000000000", columns=[ColumnNear(col=1, chars=chars)])
    ctx2 = _Ctx(imgs, other, set(range(n)))
    assert run(ctx2, True) == base and "读 3b 0" in ctx2.logs[0]


# ── book_knn（库钉版，CV3 #2019）：3b 出前段，4d 用 book_knn_settle 定档；按 (格 id, 库指纹) 取 ─────────────

@pytest.mark.parametrize("k", ["base", "b_only", "b_tight", "bg", "mix"])
def test_book_knn_read_3b_same_as_local(bk_models, k):  # noqa: F811
    from open_guji_cv.steps.seed_admit_shapes import _book_knn_pass
    from test_glyph_near_book_knn import REFS, _imgs as _bk_imgs

    imgs = _bk_imgs()
    n = len(imgs)
    refs = {f"b:1:1:{i + 1}": REFS[i % len(REFS)] for i in range(n)}

    def cells():
        return [NS(id=f"b:1:1:{i + 1}", slot=i + 1, sub=None, char="口", admit=False, provenance="match", channel="",
                   doubts=["near_form"], evidence={"group": {"id": "t"}}) for i in range(n)]

    def run(ctx, on):
        cs = cells()
        p = NS(group_flow_book_knn={"t": str(bk_models[k])}, patch_missing="error",
               group_flow_near_from_3b=["book_knn"] if on else [])
        amap = {cid: (ref,) for cid, ref in refs.items() if ref is not None}
        d = _book_knn_pass(p, [NS(col=1, chars=cs)], amap, ctx, 1)
        return d, [(c.char, c.admit, c.channel, copy.deepcopy(c.evidence)) for c in cs]

    base = run(_Ctx(imgs, None, set(range(n))), False)
    outs = NM.load_method("book_knn", str(bk_models[k])).score(imgs, "b")
    covered = set(range(0, n, 2))
    chars = [NearRec(id=c.id, slot=c.slot, group="t", trigger="cands",
                     methods=[NearMethodOut(method="book_knn:t", sims=o["sims"], evidence=o["evidence"])])
             for i, (c, o) in enumerate(zip(cells(), outs)) if i in covered]
    sha = "t:book_knn=" + NM.lib_fingerprint(str(bk_models[k]))
    ctx = _Ctx(imgs, PageNear(page=1, methods_sha=sha, columns=[ColumnNear(col=1, chars=chars)]), set(range(n)) - covered)
    assert run(ctx, True) == base
    assert f"book_knn 判法结果 读 3b {len(covered)}" in ctx.logs[0]
    # 库版本不同：取不到，全部本地现算
    ctx2 = _Ctx(imgs, PageNear(page=1, methods_sha="t:book_knn=0000000000000000",
                               columns=[ColumnNear(col=1, chars=chars)]), set(range(n)))
    assert run(ctx2, True) == base and "读 3b 0" in ctx2.logs[0]


# ── near_knn（伪组 _guard，CV3 #2022）：3b 出距离，4d 用 near_knn_settle 按候选定档；settle 给 None 的格本地现算 ──────

@pytest.mark.parametrize("k", ["base", "loose", "guard", "tie"])
def test_near_knn_read_3b_same_as_local(nk_models, k):  # noqa: F811
    from open_guji_cv.steps.glyph_near import trigger_groups
    from open_guji_cv.steps.seed_admit_shapes import _near_knn_pass
    from test_glyph_near_near_knn import _cells, bar, box, cross

    imgs = [box(1), cross(-1), box(-2), bar(0), cross(2), box(2), box(-1), cross(1), box(0), cross(0)]
    n = len(imgs)

    class Ctx(_Ctx):
        book = NS(codepoints=None)

    def run(ctx, on):
        cells, mmap, amap = _cells(imgs)
        p = NS(group_flow_near_knn=str(nk_models[k]), patch_missing="error", near_knn_gap=True,
               group_flow_near_from_3b=["near_knn"] if on else [])
        for stage in ("near", "gap"):
            _near_knn_pass(p, [NS(col=1, chars=cells)], amap, mmap, ctx, 1, stage=stage)
        return [(c.char, c.admit, c.channel, c.provenance, c.doubts, json.dumps(c.evidence, ensure_ascii=False))
                for c in cells]

    base = run(Ctx(imgs, None, set(range(n))), False)
    cells, mmap, _ = _cells(imgs)
    m = NM.load_method("near_knn", str(nk_models[k]))
    groups = {"_guard": {"trigger": "guard", "gap": True, "methods": {"near_knn": str(nk_models[k])}}}
    recs = []
    for i, (c, g) in enumerate(zip(cells, imgs)):
        r = mmap[c.id]
        t = trigger_groups(r.candidates, r.char, groups, r)
        if t and i != 4:                                         # 第 5 格当 3b 没触发
            ev = m.score([g], "b", cells=[{"char": r.char, "candidates": r.candidates}])[0]["evidence"]
            recs.append(NearRec(id=c.id, slot=c.slot, group="_guard", trigger=t[0][1],
                                methods=[NearMethodOut(method="near_knn:_guard", evidence=ev)]))
    sha = "_guard:near_knn=" + NM.lib_fingerprint(str(nk_models[k]))
    ctx = Ctx(imgs, PageNear(page=1, methods_sha=sha, columns=[ColumnNear(col=1, chars=recs)]), set(range(n)))
    assert run(ctx, True) == base
    got = " ".join(ctx.logs)
    assert "near_knn(near) 判法结果" in got and "near_knn(gap) 判法结果" in got
    assert sum(int(x.split("读 3b ")[1].split("｜")[0]) for x in ctx.logs) >= 3


# ── stroke_veto（CV3 #2024）：按 (格 id, {path, group} 指纹) 取；降不降审仍在第四步 ──────────────

@pytest.mark.parametrize("k", ["base", "hi_t", "no_z", "ch"])
@pytest.mark.parametrize("group,admitted_as", [("jys", "己"), ("jys", "已"), ("qg", "千"), ("qg", "干")])
def test_stroke_veto_read_3b_same_as_local(sv_models, k, group, admitted_as):  # noqa: F811
    from open_guji_cv.steps.seed_admit_shapes import _stroke_veto_pass
    from test_glyph_near_stroke_veto import _imgs as _sv_imgs

    imgs = _sv_imgs(group)
    n = len(imgs)

    def recs():
        return [NS(id=f"b:1:1:{i + 1}", slot=i + 1, sub=None, char=admitted_as, admit=True, evidence={},
                   provenance="match", channel="match_ref", doubts=[]) for i in range(n)]

    def run(ctx, on):
        rs = recs()
        p = NS(stroke_veto=str(sv_models[k]), patch_missing="error",
               group_flow_near_from_3b=["stroke_veto"] if on else [])
        d = _stroke_veto_pass(p, [NS(col=1, chars=rs)], ctx, 1)
        return d, [(r.char, r.admit, r.channel, r.doubts, copy.deepcopy(r.evidence)) for r in rs]

    base = run(_Ctx(imgs, None, set(range(n))), False)
    spec = {"path": str(sv_models[k]), "group": group}
    outs = NM.load_method("stroke_veto", spec).score(imgs, "b")
    covered = set(range(0, n, 2))
    chars = [NearRec(id=r.id, slot=r.slot, group=group, trigger="cands",
                     methods=[NearMethodOut(method=f"stroke_veto:{group}", sims=o["sims"], evidence=o["evidence"])])
             for i, (r, o) in enumerate(zip(recs(), outs)) if i in covered]
    sha = f"{group}:" + NM.method_fingerprint("stroke_veto", spec)
    ctx = _Ctx(imgs, PageNear(page=1, methods_sha=sha, columns=[ColumnNear(col=1, chars=chars)]), set(range(n)) - covered)
    got = run(ctx, True)
    assert got == base
    if ctx.logs:
        assert "stroke_veto 判法结果" in ctx.logs[0]
