# -*- coding: utf-8 -*-
"""Step6b `group_decide`（GUJI-49 PR1）：自造数据。

守三件事：① 查表与弃权语义；② 默认关；③ 加这一步不让任何**现有** Step 的指纹相关文件变。
"""
from __future__ import annotations

import json

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_align_ref, page_match, write_product
from open_guji_cv.core.engine import Engine
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps import group_decide as gd
from open_guji_cv.utils.ji_yi_si_clf import ctx_key

PAGE = 1
# 一列 5 格：山 日 水 曰 山。整理本全对位；库只在 1/3/5 格给 same。
MATCH = [dict(slot=1, verdict="same", char="山"), dict(slot=2, verdict="unsure"),
         dict(slot=3, verdict="same", char="水"), dict(slot=4, verdict="unsure"),
         dict(slot=5, verdict="same", char="山")]
ALIGN = [dict(slot=1, align_char="山"), dict(slot=2, align_char="日"), dict(slot=3, align_char="水"),
         dict(slot=4, align_char="曰"), dict(slot=5, align_char="山")]


def _table(tmp_path, cells, *, group="ry", schema="group_clf/1"):
    p = tmp_path / f"{group}.json"
    p.write_text(json.dumps({"schema": schema, "group": group, "ver": f"{group}-t", "cells": cells}),
                 encoding="utf-8")
    gd._load_table.cache_clear()
    return str(p)


def _run(tmp_path, tables, *, align=ALIGN, anchored=True):
    book = make_book(group_decide=True)
    ctx = make_ctx(tmp_path, book)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, recs=MATCH))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(PAGE, recs=align, anchored=anchored))
    step = STEPS["group_decide"]
    p = gd.GroupDecideParams(group_tables=tables or {})
    ctx.params_for = lambda s, _p=p: _p            # 单步试跑：直接给参数
    return step.run_page(ctx, PAGE)["group_decision"]


def _cell(ch, ctx, **kw):
    return {"ctx": ctx, "char": ch, "conf": None, "why": "agree", **kw}


def test_hit_and_abstain_reasons(tmp_path):
    # 第 2 格（日）：左「山」右「水曰山」；第 4 格（曰）：左「山日水」右「山」
    c2 = ctx_key("山", "水曰山")
    t = _table(tmp_path, {
        "tbook:1:1:2": _cell("曰", c2),                       # 给字
        "tbook:1:1:4": _cell("曰", "deadbeef0000"),            # ctx 不符
    })
    dec = _run(tmp_path, {"ry": t})
    by = {c.id: c for c in dec.cells}
    assert by["tbook:1:1:2"].char == "曰" and by["tbook:1:1:2"].group == "ry" and by["tbook:1:1:2"].ref == "日"
    assert by["tbook:1:1:4"].char is None and by["tbook:1:1:4"].why == "ctx_mismatch"
    assert all(c.action == "none" for c in dec.cells)          # PR1 恒 none
    assert set(by) == {"tbook:1:1:2", "tbook:1:1:4"}            # 非成员格（山／水）不出现


def test_cache_miss_wrong_group_and_out_of_group_char(tmp_path):
    t = _table(tmp_path, {"tbook:1:1:2": _cell("山", ctx_key("山", "水曰山"))})   # 给的字不在组内
    dec = _run(tmp_path, {"ry": t})
    by = {c.id: c for c in dec.cells}
    assert by["tbook:1:1:2"].char is None
    assert by["tbook:1:1:4"].why == "cache_miss"
    bad = _table(tmp_path, {}, group="jys", schema="group_clf/2")
    assert gd.lookup(gd._load_table(bad), "jys", "x", "", "")["why"] == "ver_mismatch"


def test_default_off_and_unanchored_are_empty(tmp_path):
    assert _run(tmp_path, None).cells == []                     # 没配表
    t = _table(tmp_path, {"tbook:1:1:2": _cell("曰", ctx_key("山", "水曰山"))})
    assert _run(tmp_path, {"ry": t}, anchored=False).cells == []


def test_book_switch_filters_step(tmp_path):
    from open_guji_cv.core.pipeline import load_pipeline
    pl = load_pipeline("keben_body_v2")
    assert "group_decide" in pl.steps                     # 拓扑里在，是否跑看书级开关
    for on in (False, True):
        ctx = make_ctx(tmp_path / str(on), make_book(group_decide=on))
        eng = Engine(ctx.book, pl, store=ctx.store, cache=ctx.cache, log=lambda s: None)
        assert ("group_decide" in eng._enabled(pl.steps)) is on


def test_adding_step_changes_no_existing_fingerprint_files():
    """本 PR 新增／追加的文件，不在任何**现有** Step 的指纹相关文件集（自身模块＋code_deps）里。
    不用 `release_check.step_file_map`：测试里 `REPO_ROOT` 被 conftest 挪走，它算不出相对路径。"""
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    mine = {"open_guji_cv/steps/group_decide.py", "open_guji_cv/products/kinds/group.py",
            "open_guji_cv/steps/__init__.py", "open_guji_cv/products/kinds/__init__.py",
            "open_guji_cv/core/book.py", "open_guji_cv/core/engine.py",
            "open_guji_cv/core/spec.py"}              # spec.py：本 PR 不改，列进来是守「谁也别去改它」
    for sid, step in STEPS.items():
        if sid == "group_decide":
            continue
        for m in (type(step).__module__, *step.spec.code_deps):
            origin = Path(importlib.util.find_spec(m).origin).resolve().relative_to(root).as_posix()
            assert origin not in mine - {"open_guji_cv/core/spec.py"}, (sid, m)
