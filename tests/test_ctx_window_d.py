# -*- coding: utf-8 -*-
"""Step6b PR2 方案 D（GUJI-208lf）：`utils/ctx_window` 与 `seed_admit.ctx_align_ref`。自造数据。

守：① 窗口纯函数（对位字／缺 □／页首尾截断／宽度）；② 键不随放行态漂移；③ 骨架不剔 excluded、
列按号升序展平；④ group_decide 与 seed_admit 同键；⑤ 开关关＝旧行为、`params_hash` 不变、开＝进 dump。
"""
from __future__ import annotations

import json

import open_guji_cv.steps  # noqa: F401
import open_guji_cv.utils.ji_yi_si_clf as jc
import open_guji_cv.utils.ry_group as ry
from helpers import make_book, make_ctx, page_align_ref, page_match, write_product
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.steps import group_decide as gd
from open_guji_cv.steps import seed_admit as sa
from open_guji_cv.utils.ctx_window import CTX_WIDTH, ref_ctx, ref_ctx_key, ref_window
from open_guji_cv.utils.ji_yi_si_clf import ctx_key


# ---------- ① 纯函数 ----------
def test_window_basic_edges_missing_and_width():
    ids = ["a", "b", "c", "d", "e"]
    ref = {"a": "山", "b": "日", "c": None, "d": "水", "e": "木"}
    assert ref_ctx(ids, ref, 1) == ("山", "□水木")             # 缺字 c → □
    assert ref_ctx(ids, ref, 0) == ("", "日□水木")             # 页首：左空
    assert ref_ctx(ids, ref, 4) == ("山日□水", "")              # 页尾：右空
    assert ref_window(ids, ref, 1, 1, width=2) == "□水"         # 宽度截断
    assert ref_window(ids, ref, 4, -1, width=2) == "□水"
    # 键：左文取到最近 □ 之后，右文取到第一个 □ 之前（ctx_key 本身的规则）
    assert ref_ctx_key(ids, ref, 1) == ctx_key("山", "□水木")
    assert ref_ctx_key(ids, ref, 3) == ctx_key("山日□", "木") == ctx_key("", "木")
    big = [f"x{i}" for i in range(80)]
    r2 = {k: "山" for k in big}
    assert len(ref_window(big, r2, 40, -1)) == CTX_WIDTH == len(ref_window(big, r2, 40, 1))


# ---------- ② ③ seed_admit 侧：不随放行态漂移、不剔 excluded、列升序 ----------
def _rec(i, col, slot, *, char=None, admit=False, doubts=()):
    return AdmitRec(id=f"tbook:1:{col}:{slot}", slot=slot, char=char, admit=admit,
                    channel="match_solo" if admit else None, doubts=list(doubts))


def _amap(cols):
    return {f"tbook:1:{c}:{s}": (ch, "equal") for c, chs in cols for s, ch in enumerate(chs, 1)}


def _ry_cache(tmp_path, cid, ctx):
    p = tmp_path / "ry.json"
    v = {"muse": ["日", "日"], "gemini": ["日", "日"], "haiku": ["日"]}
    p.write_text(json.dumps({"cells": {cid: {"ctx": ctx, "ver": "ry-v2", "votes": v}}}), encoding="utf-8")
    ry._load.cache_clear()
    return str(p)


def _page(*, neighbour_admit=False, excluded_mid=False, reverse_cols=False):
    """列1＝山 [水] 木；列2＝日（目标）山。[水] 可设为 excluded。邻格可设为已放行且字与整理本不同。"""
    c1 = [_rec(1, 1, 1, char="松" if neighbour_admit else None, admit=neighbour_admit),
          _rec(2, 1, 2, doubts=["excluded"] if excluded_mid else []),
          _rec(3, 1, 3, char="杉" if neighbour_admit else None, admit=neighbour_admit)]
    c2 = [_rec(4, 2, 1), _rec(5, 2, 2)]
    cols = [ColumnAdmit(col=1, chars=c1), ColumnAdmit(col=2, chars=c2)]
    return cols[::-1] if reverse_cols else cols


AMAP = _amap([(1, "山水木"), (2, "日山")])
TID = "tbook:1:2:1"
D_KEY = ctx_key("山水木", "山")          # 方案 D：整页、对位字、不剔 excluded


def test_d_key_hits_and_is_independent_of_admission(tmp_path):
    t = _ry_cache(tmp_path, TID, D_KEY)
    for adm in (False, True):                                 # 邻格放行（且放行字≠整理本）与否，键不变
        out = _page(neighbour_admit=adm)
        assert sa._ry_group_pass(out, AMAP, t, ctx_ref=True) == 1
        assert out[1].chars[0].channel == "ry_group"
    out = _page(neighbour_admit=True)                         # 旧口径：邻格放行字进窗口 → 键漂移 → 失配
    assert sa._ry_group_pass(out, AMAP, t, ctx_ref=False) == 0
    assert out[1].chars[0].evidence["ry_group"]["why"] == "ctx_mismatch"


def test_excluded_cell_stays_in_window_but_is_never_a_target(tmp_path):
    t = _ry_cache(tmp_path, TID, D_KEY)
    out = _page(excluded_mid=True)
    assert sa._ry_group_pass(out, AMAP, t, ctx_ref=True) == 1          # 窗口跨过 excluded 格：D 仍含「水」
    old = _page(excluded_mid=True)
    assert sa._ry_group_pass(old, AMAP, t, ctx_ref=False) == 0         # 旧口径剔掉它：窗口成「山木」→ 失配
    assert old[1].chars[0].evidence["ry_group"]["why"] == "ctx_mismatch"
    # excluded 格自己是日曰组成员时也不当目标
    amap2 = dict(AMAP, **{"tbook:1:1:2": ("日", "equal")})
    t2 = _ry_cache(tmp_path, "tbook:1:1:2", ctx_key("山", "木日山"))
    out2 = _page(excluded_mid=True)
    assert sa._ry_group_pass(out2, amap2, t2, ctx_ref=True) == 0
    assert "ry_group" not in (out2[0].chars[1].evidence or {})


def test_columns_flattened_ascending_and_page_edges(tmp_path):
    t = _ry_cache(tmp_path, TID, D_KEY)
    out = _page(reverse_cols=True)                           # 列在产物里倒序存
    assert sa._ry_group_pass(out, AMAP, t, ctx_ref=True) == 1
    # 页尾：最后一格的右文为空；页首：第一格的左文为空
    ids, ref, idx = sa._d_skeleton(_page(), AMAP)
    assert ref_ctx(ids, ref, idx[ids[0]])[0] == "" and ref_ctx(ids, ref, idx[ids[-1]])[1] == ""
    assert ids == ["tbook:1:1:1", "tbook:1:1:2", "tbook:1:1:3", "tbook:1:2:1", "tbook:1:2:2"]


def test_unaligned_neighbour_is_box(tmp_path):
    amap = {k: v for k, v in AMAP.items() if k != "tbook:1:1:3"}      # 木 缺对位字 → □
    t = _ry_cache(tmp_path, TID, ctx_key("山水□", "山"))             # 左文被 □ 收窄成空 → 与 ctx_key("","山") 同键
    assert ctx_key("山水□", "山") == ctx_key("", "山")
    assert sa._ry_group_pass(_page(), amap, t, ctx_ref=True) == 1


# ---------- jys：只换查表键，规则 classify 仍用旧窗口 ----------
def test_jys_table_key_uses_d_but_rule_keeps_old(tmp_path):
    p = tmp_path / "jys.json"
    cid = "tbook:1:2:1"
    amap = _amap([(1, "而他"), (2, "己山")])
    d_ctx = ctx_key("而他", "山")
    p.write_text(json.dumps({"cells": {cid: {"ctx": d_ctx, "llm": ["已", "已"], "lr": "已", "lr_margin": 0.9}}}),
                 encoding="utf-8")
    jc._load.cache_clear()
    params = sa.SeedAdmitParams(ji_yi_si_clf=True, ji_yi_si_clf_table=str(p))

    def run(ctx_ref):
        cols = [ColumnAdmit(col=1, chars=[_rec(1, 1, 1, char="而", admit=True), _rec(2, 1, 2, char="松", admit=True)]),
                ColumnAdmit(col=2, chars=[_rec(3, 2, 1, char="己"), _rec(4, 2, 2, char="山", admit=True)])]
        seq = [r for c in cols for r in c.chars]
        dctx = sa._d_skeleton(cols, amap) if ctx_ref else None
        r = seq[2]
        sa._ji_yi_si_clf_cell(r, seq, 2, amap, params, dctx)
        return r.evidence["ji_yi_si_clf"]
    on, off = run(True), run(False)
    assert on["suggest"]["why"] != "ctx_mismatch" and on["suggest"]["llm"] == ["已", "已"]   # D 键命中
    assert off["suggest"]["why"] == "ctx_mismatch"                    # 旧窗口含放行字「松」→ 失配
    assert on["rule"] == off["rule"]                                  # 规则输入不变


# ---------- ④ group_decide 与 seed_admit 同键 ----------
def test_group_decide_and_seed_admit_same_key(tmp_path):
    book = make_book(group_decide=True)
    ctx = make_ctx(tmp_path, book)
    recs1 = [dict(slot=1, verdict="same", char="松"), dict(slot=2, verdict="unsure"), dict(slot=3, verdict="same", char="木")]
    recs2 = [dict(slot=1, verdict="unsure"), dict(slot=2, verdict="same", char="山")]
    m1, m2 = page_match(1, recs=recs1, col=1), page_match(1, recs=recs2, col=2)
    m1.columns += m2.columns
    m1.columns.reverse()
    write_product(ctx, "glyph_match", 1, glyph_match=m1)
    a1 = page_align_ref(1, recs=[dict(slot=1, align_char="山"), dict(slot=2, align_char="水"), dict(slot=3, align_char="木")], col=1)
    a2 = page_align_ref(1, recs=[dict(slot=1, align_char="日"), dict(slot=2, align_char="山")], col=2)
    a1.chars += a2.chars
    write_product(ctx, "align_ref", 1, align_ref=a1)
    tpath = tmp_path / "ry.json"
    tpath.write_text(json.dumps({"schema": "group_clf/1", "group": "ry", "ver": "t",
                                 "cells": {TID: {"ctx": D_KEY, "char": "日", "conf": None, "why": "agree"}}}),
                     encoding="utf-8")
    gd._load_table.cache_clear()
    p = gd.GroupDecideParams(group_tables={"ry": str(tpath)})
    ctx.params_for = lambda s, _p=p: _p
    cells = {c.id: c for c in STEPS["group_decide"].run_page(ctx, 1)["group_decision"].cells}
    assert cells[TID].char == "日"
    # 同一页，seed_admit 侧的键：同一张表（把 TID 的 ctx 换成同一 D_KEY 的 ry-v2 条目）
    t = _ry_cache(tmp_path, TID, D_KEY)
    assert sa._ry_group_pass(_page(), AMAP, t, ctx_ref=True) == 1


# ---------- ⑤ 开关 ----------
def test_switch_default_off_hash_unchanged_and_on_in_dump():
    base = sa.SeedAdmitParams().model_dump()
    assert "ctx_align_ref" not in base
    assert sa.SeedAdmitParams(ctx_align_ref=False).model_dump() == base
    assert sa.SeedAdmitParams(ctx_align_ref=True).model_dump().get("ctx_align_ref") is True
    assert "open_guji_cv.utils.ctx_window" in STEPS["seed_admit"].spec.code_deps


def test_run_page_off_is_byte_identical_and_on_hits(tmp_path, monkeypatch):
    """整步试跑：缺省／显式关 → 产物逐字节相同；开 → 同页同表命中（该页放行态与整理本一致，两口径同键）。"""
    from open_guji_cv.core.step import RunContext
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore
    recs = [dict(slot=1, verdict="same", cov=1.0, wmax=0.0, char="山", candidates=[("山", 1.0)]),
            dict(slot=2, verdict="unsure", cov=0.5, wmax=0.0, candidates=[("木", 0.5), ("本", 0.4)]),
            dict(slot=3, verdict="same", cov=1.0, wmax=0.0, char="水", candidates=[("水", 1.0)])]
    arecs = [dict(slot=1, align_char="山"), dict(slot=2, align_char="日"), dict(slot=3, align_char="水")]
    t = _ry_cache(tmp_path, "tbook:1:1:2", ctx_key("山", "水"))

    def go(tag, **kw):
        base = tmp_path / tag
        monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(base / "p"))
        monkeypatch.setenv("GUJI_CACHE_DIR", str(base / "c"))
        c = RunContext(make_book("tbook"), ProductStore(base / "p"), ImageCache(base / "c"),
                       params={"seed_admit": sa.SeedAdmitParams(ry_group=True, ry_group_cache=t, **kw)},
                       log=lambda s: None)
        write_product(c, "glyph_match", 1, glyph_match=page_match(1, "tbook", recs=recs, col=1))
        write_product(c, "align_ref", 1, align_ref=page_align_ref(1, "tbook", recs=arecs, col=1))
        return STEPS["seed_admit"].run_page(c, 1)["seed_admit"]
    default, off, on = go("a"), go("b", ctx_align_ref=False), go("c", ctx_align_ref=True)
    assert default.model_dump_json() == off.model_dump_json()
    hit = {r.slot: r for cc in on.columns for r in cc.chars}[2]
    assert hit.admit and hit.channel == "ry_group"
