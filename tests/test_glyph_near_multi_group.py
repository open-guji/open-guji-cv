"""3b `glyph_near` 一格多组（2026-11-28，CV3／CV4 定）：一格触发几个组就每组一条 NearRec；`PageNear.by_id` 保留旧行为，
`by_id_all`／`get` 按组取；收尾 `glyph_analyzer` 的 `near` 改成按组，多组时 p 的保守合并规则。

数据全在测试里造（rr_shape 模型、字块图同 `test_glyph_near_rr_shape.py`）。
"""
from __future__ import annotations

import itertools

import numpy as np
import pytest

from open_guji_cv.groups import rr_shape
from open_guji_cv.products.kinds.read import ColumnNear, FinalCand, FinalRec, NearMethodOut, NearRec, PageNear
from open_guji_cv.steps.glyph_analyzer import merge_cell
from open_guji_cv.steps.glyph_near import trigger_group, trigger_groups

from helpers import make_book, make_ctx, page_chars, page_match, run_steps, write_product
from test_glyph_near_rr_shape import model_file  # noqa: F401
from test_rr_shape import ba, ren, ru

GONG = {"chars": ["宫", "宮", "官"], "fold": {"宮": "宫"}, "trigger": "member"}
GUAN = {"chars": ["官", "宦"], "trigger": "cands", "topk": 3}


# ── 触发 ─────────────────────────────────────────────────────────────

def test_trigger_groups_gives_every_group_sorted_and_trigger_group_first():
    g = {"guan": GUAN, "gong": GONG, "rr": {"chars": ["人", "入", "八"], "trigger": "cands"}}
    assert trigger_groups([("官", 0.9), ("宦", 0.8)], "官", g) == [("gong", "member"), ("guan", "cands")]
    assert trigger_group([("官", 0.9), ("宦", 0.8)], "官", g) == ("gong", "member")      # 旧口：按组 id 第一个
    assert trigger_groups([("宦", 0.9)], "宦", g) == [("guan", "cands")]
    assert trigger_groups([("言", 0.9)], "言", g) == [] and trigger_group([("言", 0.9)], "言", g) is None
    assert trigger_groups([], None, g) == []


# ── 产物读口 ──────────────────────────────────────────────────────────

def _nr(cid, group, sims=None, method=None, ev=None, trigger="cands"):
    return NearRec(id=cid, slot=int(cid.rsplit(":", 1)[1]), group=group, trigger=trigger,
                   methods=[NearMethodOut(method=method or f"m:{group}", sims=sims or {}, evidence=ev or {})])


def test_page_near_by_id_keeps_first_group_by_id_all_and_get():
    pn = PageNear(page=1, columns=[ColumnNear(col=1, chars=[_nr("b:1:1:1", "gong"), _nr("b:1:1:1", "guan"),
                                                            _nr("b:1:1:2", "guan")])])
    assert {k: v.group for k, v in pn.by_id().items()} == {"b:1:1:1": "gong", "b:1:1:2": "guan"}
    assert {k: [r.group for r in v] for k, v in pn.by_id_all().items()} == {"b:1:1:1": ["gong", "guan"],
                                                                             "b:1:1:2": ["guan"]}
    assert pn.get("b:1:1:1", "guan").group == "guan" and pn.get("b:1:1:2", "gong") is None
    assert pn.get("b:9:9:9", "gong") is None
    # 落盘再读回来同样（产物形状没变：仍是 columns[].chars[] 的 NearRec 列表）
    back = PageNear.model_validate_json(pn.model_dump_json())
    assert back == pn and [r.group for r in back.by_id_all()["b:1:1:1"]] == ["gong", "guan"]


def test_final_rec_near_groups_reads_old_and_new_shape():
    old = FinalRec(id="b:1:1:1", slot=1, near={"group": "rr", "trigger": "cands", "methods": {"rr_shape": {"char": "人"}}})
    assert old.near_groups() == {"rr": {"trigger": "cands", "methods": {"rr_shape": {"char": "人"}}}}
    new = FinalRec(id="b:1:1:1", slot=1, near={"rr": {"trigger": "cands", "methods": {}}})
    assert new.near_groups() == new.near
    assert FinalRec(id="b:1:1:1", slot=1).near_groups() == {}


# ── 收尾：单组与 0.1 版逐键一致 ────────────────────────────────────────

def _merge_cell_v01(match_rec, near_rec, calibrators, topk, algo):
    """收尾 0.1（cv dev 7239311d）的 merge_cell 里 3a＋3b 那一段原样抄来，当单组时的对照。"""
    cands, order = {}, []
    for c, s in (match_rec.candidates or [])[:topk]:
        c = str(c)
        if c not in cands:
            cands[c] = FinalCand(char=c, evidence={"a": {"sim": round(float(s), 4), "algo": algo}})
            order.append(c)
    p_src = ""
    if near_rec is not None:
        for mo in near_rec.methods:
            for c, s in mo.sims.items():
                fc = cands.get(c)
                if fc is None:
                    fc = cands[c] = FinalCand(char=c)
                    order.append(c)
                fc.evidence.setdefault("b", {})[mo.method] = s        # B3（11-28）起 b 不再记 group，键「方法:组」自带组
            m = calibrators.get(mo.method)
            ps = m.calibrate(mo.sims) if m is not None else None
            if ps and not p_src:
                p_src = f"near:{mo.method}"
                for c, pv in ps.items():
                    if c in cands:
                        cands[c].p = pv
                for a, b in (getattr(m, "merge", None) or {}).items():
                    if a in cands and b in ps:
                        cands[a].evidence.setdefault("b", {})["same_as"] = b
    rank = {c: i for i, c in enumerate(order)}
    for fc in cands.values():
        if (fc.evidence.get("b") or {}).get("same_as"):
            fc.p = None
    out = sorted(cands.values(), key=lambda fc: (-(fc.p if fc.p is not None else -1.0), rank[fc.char]))
    meth = {}
    for mo in (near_rec.methods if near_rec is not None else []):
        meth[mo.method.split(":", 1)[0]] = {"method": mo.method.split(":", 1)[0], **mo.evidence}
    near = {"group": near_rec.group, "trigger": near_rec.trigger, "methods": meth} if near_rec is not None else {}
    return out, p_src, near


class _Cal:
    def __init__(self, ps, merge=None):
        self.ps, self.merge = ps, merge or {}

    def calibrate(self, sims):
        return dict(self.ps) if sims else None


def _match_rec(cands):
    return page_match(recs=[{"slot": 1, "verdict": "unsure", "candidates": cands}]).columns[0].chars[0]


SINGLE_CASES = [
    # (3a 候选, 方法们 [(方法全名, sims, evidence)], 校准器)
    ([("官", 0.9), ("宫", 0.89)], [("cnn_small:gong", {"官": 0.2, "宫": 0.8, "宮": 0.8}, {"fold": "fold1"})],
     {"cnn_small:gong": _Cal({"宫": 0.9, "官": 0.1}, {"宮": "宫"})}),
    ([("官", 0.9)], [("cnn_small:gong", {"官": 0.3, "宫": 0.7}, {})], {}),
    ([("人", 0.9), ("八", 0.89)], [("rr_shape:rr", {"八": 1.0, "人": 0.0, "入": 0.0}, {"char": "八", "why": "agree"})], {}),
    ([("人", 0.9)], [("rr_shape:rr", {}, {"error": "patch_missing", "detail": "x"}),
                     ("zz:rr", {"人": 0.6, "入": 0.4}, {"k": 1})], {"zz:rr": _Cal({"人": 0.7, "入": 0.3})}),
    ([("人", 0.9)], [("aa:rr", {"人": 0.6, "入": 0.4}, {}), ("zz:rr", {"人": 0.6, "入": 0.4}, {})],
     {"aa:rr": _Cal({"人": 0.55, "入": 0.45}), "zz:rr": _Cal({"人": 0.7, "入": 0.3})}),      # 组内取第一个出 p 的
]


@pytest.mark.parametrize("case", SINGLE_CASES)
def test_single_group_same_as_v01(case):
    cands3a, meths, cal = case
    grp = meths[0][0].split(":", 1)[1]
    nr = NearRec(id="tbook:1:1:1", slot=1, group=grp, trigger="close",
                 methods=[NearMethodOut(method=m, sims=s, evidence=e) for m, s, e in meths])
    want_c, want_src, want_near = _merge_cell_v01(_match_rec(cands3a), nr, cal, 5, "elastic")
    for arg in (nr, [nr]):                                              # 单条、列表两种都认
        got = merge_cell(_match_rec(cands3a), arg, cal, 5, "elastic")
        assert [c.model_dump() for c in got.cands] == [c.model_dump() for c in want_c]     # 字、p、evidence 逐键
        assert got.p_src == want_src
        g = dict(got.near[grp])
        g.pop("p", None), g.pop("p_src", None)
        assert {grp: g} == FinalRec(id="x", slot=1, near=want_near).near_groups()       # near 只是换了形状


# ── 收尾：多组 ────────────────────────────────────────────────────────

def test_multi_group_one_calibrated_gives_its_p():
    gong = _nr("tbook:1:1:1", "gong", {"官": 0.2, "宫": 0.8}, "cnn_small:gong", {"fold": "fold1"}, "member")
    guan = _nr("tbook:1:1:1", "guan", {"官": 0.6, "宦": 0.4}, "xx:guan", {"char": "官"})
    cal = {"cnn_small:gong": _Cal({"宫": 0.9, "官": 0.1})}
    for arg in ([gong, guan], [guan, gong]):                            # 进来的次序不影响
        r = merge_cell(_match_rec([("官", 0.9), ("宫", 0.89)]), arg, cal, 5, "elastic")
        by = {c.char: c for c in r.cands}
        assert r.p_src == "near:cnn_small:gong" and by["宫"].p == 0.9 and by["官"].p == 0.1 and by["宦"].p is None
        assert by["官"].evidence["b"] == {"cnn_small:gong": 0.2, "xx:guan": 0.6}      # 几个组都给了分：键自带组（B3）
        assert by["宦"].evidence["b"] == {"xx:guan": 0.4}
        assert r.near == {"gong": {"trigger": "member", "methods": {"cnn_small": {"method": "cnn_small", "fold": "fold1"}},
                                   "p": {"宫": 0.9, "官": 0.1}, "p_src": "near:cnn_small:gong"},
                          "guan": {"trigger": "cands", "methods": {"xx": {"method": "xx", "char": "官"}}}}


def test_multi_group_both_calibrated_gives_no_p():
    gong = _nr("tbook:1:1:1", "gong", {"官": 0.2, "宫": 0.8}, "cnn_small:gong")
    guan = _nr("tbook:1:1:1", "guan", {"官": 0.6, "宦": 0.4}, "xx:guan")
    cal = {"cnn_small:gong": _Cal({"宫": 0.9, "官": 0.1}), "xx:guan": _Cal({"官": 0.7, "宦": 0.3})}
    r = merge_cell(_match_rec([("官", 0.9), ("宫", 0.89)]), [gong, guan], cal, 5, "elastic")
    assert r.p_src == "" and all(c.p is None for c in r.cands)
    assert [c.char for c in r.cands] == ["官", "宫", "宦"]                  # 没 p：3a 序，3b 新增的排后
    assert r.near["gong"]["p"] == {"宫": 0.9, "官": 0.1} and r.near["gong"]["p_src"] == "near:cnn_small:gong"
    assert r.near["guan"]["p"] == {"官": 0.7, "宦": 0.3} and r.near["guan"]["p_src"] == "near:xx:guan"
    # 序列化：没 p 的 near 组不带 p 键
    r2 = merge_cell(_match_rec([("官", 0.9)]), [gong, guan], {}, 5, "elastic")
    assert all(set(v) == {"trigger", "methods"} for v in r2.near.values())


# ── 端到端：同一格触发两个组 ────────────────────────────────────────────

def test_glyph_near_multi_group_end_to_end(tmp_path, model_file):
    groups = {"rr": {"ref": "rr", "trigger": "cands", "methods": {"rr_shape": str(model_file)}},
              "rx": {"chars": ["人", "大"], "trigger": "member", "methods": {"rr_shape": str(model_file)}}}
    book = make_book("tbook", params={"glyph_near": {"groups": groups}, "glyph_analyzer": {"enabled": True}})
    ctx = make_ctx(tmp_path, book, raw={1: np.full((400, 300), 255, np.uint8)})
    imgs = {1: ren(), 2: ru(), 3: ba()}
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(recs=[
        {"slot": 1, "verdict": "unsure", "candidates": [("人", 0.90), ("入", 0.89)]},   # rr、rx 都触发
        {"slot": 2, "verdict": "unsure", "candidates": [("入", 0.90), ("人", 0.89)]},   # 只 rr（rx 要首位在组里）
        {"slot": 3, "verdict": "unsure", "candidates": [("大", 0.90)]},                 # 只 rx；字块图读不到
        {"slot": 4, "verdict": "same", "char": "言", "cov": 0.95}]))
    write_product(ctx, "cell_shrink", 1, char_index=page_chars(recs=[
        {"slot": s, "bbox_page": (30.0, 10.0 + 50 * s, 70.0, 50.0 + 50 * s), "patch_key": f"p0001c01s{s}"}
        for s in range(1, 5)]))
    for s in (1, 2):
        ctx.cache.put("tbook", "char_patch", f"p0001c01s{s}", imgs[s])

    out = run_steps(ctx, 1, ["glyph_near", "glyph_analyzer"])
    pn = out["glyph_near"]
    assert [(r.id[-1], r.group) for r in pn.columns[0].chars] == [("1", "rr"), ("1", "rx"), ("2", "rr"), ("3", "rx")]
    assert {k: v.group for k, v in pn.by_id().items()} == {"tbook:1:1:1": "rr", "tbook:1:1:2": "rr", "tbook:1:1:3": "rx"}
    assert [r.group for r in pn.by_id_all()["tbook:1:1:1"]] == ["rr", "rx"]
    sha = rr_shape.fingerprint(str(model_file))
    assert pn.models == {"rr_shape:rr": sha, "rr_shape:rx": sha}
    assert pn.methods_sha.startswith("rr:rr_shape=") and ";rx:rr_shape=" in pn.methods_sha
    model = rr_shape.load(str(model_file))
    v = rr_shape.judge(imgs[1], model)
    trail = {"method": "rr_shape", **{k: v[k] for k in ("char", "why", "nn", "score", "geo") if k in v}}
    a, b = pn.get("tbook:1:1:1", "rr").methods[0], pn.get("tbook:1:1:1", "rx").methods[0]
    assert a.method == "rr_shape:rr" and b.method == "rr_shape:rx"
    assert a.evidence == b.evidence == trail and a.sims == b.sims             # 同图同方法：两组同一结论
    miss = pn.get("tbook:1:1:3", "rx").methods[0]
    assert miss.sims == {} and miss.evidence["error"] == "patch_missing"

    fin = out["glyph_analyzer"].by_id()
    c1 = fin["tbook:1:1:1"]
    assert c1.near == {"rr": {"trigger": "cands", "methods": {"rr_shape": {**trail, "model": sha}}},
                       "rx": {"trigger": "member", "methods": {"rr_shape": {**trail, "model": sha}}}}
    assert c1.p_src == "" and all(c.p is None for c in c1.cands)
    by = {c.char: c.evidence.get("b") for c in c1.cands}
    assert set(by["人"]) == {"rr_shape:rr", "rr_shape:rx"}
    assert list(fin["tbook:1:1:2"].near) == ["rr"] and list(fin["tbook:1:1:3"].near) == ["rx"]
    assert fin["tbook:1:1:3"].near["rx"]["methods"]["rr_shape"]["error"] == "patch_missing"
    assert fin["tbook:1:1:4"].near == {} and "near" not in fin["tbook:1:1:4"].model_dump(mode="json")
