# -*- coding: utf-8 -*-
"""影子预勾（overview#269）：对齐改字层网格用影子排序＋预勾。数据自己造。

守的：
1. 没有预测文件：卡片与改前一致（无 `shadow` 字段），`shadow_info.available=false`，不报错；坏文件同。
2. 有预测文件、网格：把握≥0.9 且影子字==整理本字的卡（`pre`）排最前（按把握降序），其余保持原序，
   排序发生在 `limit` 截断之前；`shadow=False` 关掉后回到原序、无 `shadow` 字段。
3. 路由：`shadow=false` 与文件指纹进缓存键（换文件／开关都不串）。
4. 事件行（node 跑 reviewClass.ts）：给 `shadowOn` 才带 `shadow_preselect`，不给与改前逐字节一致；
   预勾被点掉的行 v≠confirm 而 shadow_preselect=true。
5. 导出脚本：`shadow_picks.jsonl` → 文件格式。
"""
from __future__ import annotations

import json

import pytest

from test_replace_align_grid import (RA, _rec, _run_ts, client, env, needs_node)  # noqa: F401  复用夹具


def _write_shadow(tmp_path, cells, book="keben"):
    from open_guji_cv.review.shadow import shadow_path
    p = shadow_path(book)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": 1, "book": book, "cells": cells}, ensure_ascii=False),
                 encoding="utf-8")
    return p


KW = dict(gate_cut=False, skip_decided=False)


def test_no_shadow_file_is_noop(env):
    from open_guji_cv.review.cards import cards
    d = cards("keben", "1", 30, "review", env, cls="replace_align", cls_sub="grid", **KW)
    assert d["shadow_info"] == {"available": False, "thr": 0.9}
    assert all("shadow" not in c for c in d["cards"])
    assert [c["id"] for c in d["cards"]] == ["keben:1:1:3", "keben:1:1:4"]


def test_bad_shadow_file_is_noop(env, tmp_path):
    from open_guji_cv.review.cards import cards
    from open_guji_cv.review.shadow import shadow_path
    p = shadow_path("keben")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{不是json", encoding="utf-8")
    d = cards("keben", "1", 30, "review", env, cls="replace_align", cls_sub="grid", **KW)
    assert d["shadow_info"]["available"] is False and all("shadow" not in c for c in d["cards"])


def test_grid_sorts_pre_first_before_limit(env, tmp_path):
    from open_guji_cv.review.cards import cards
    _write_shadow(tmp_path, {
        "keben:1:1:3": {"char": "天", "conf": 0.5},       # 字对但把握不够 → 不预勾
        "keben:1:1:4": {"char": "地", "conf": 0.95},      # 预勾
        "keben:1:1:5": {"char": "宇", "conf": 0.99},      # 不在网格（manual）
    })
    d = cards("keben", "1", 30, "review", env, cls="replace_align", cls_sub="grid", **KW)
    assert d["shadow_info"]["available"] is True
    assert [c["id"] for c in d["cards"]] == ["keben:1:1:4", "keben:1:1:3"]     # 预勾的排最前
    assert d["cards"][0]["shadow"] == {"char": "地", "conf": 0.95, "pre": True}
    assert d["cards"][1]["shadow"]["pre"] is False
    # limit=1：截断发生在排序之后，第一张仍是预勾的那张
    d1 = cards("keben", "1", 1, "review", env, cls="replace_align", cls_sub="grid", **KW)
    assert [c["id"] for c in d1["cards"]] == ["keben:1:1:4"] and d1["truncated"] is True
    assert d1["class_sub_counts"]["replace_align"]["grid"] == 2
    # 影子字≠整理本字 → 不预勾，哪怕把握很高
    _write_shadow(tmp_path, {"keben:1:1:3": {"char": "夭", "conf": 0.99}})
    d2 = cards("keben", "1", 30, "review", env, cls="replace_align", cls_sub="grid", **KW)
    assert d2["cards"][0]["shadow"]["pre"] is False
    assert [c["id"] for c in d2["cards"]] == ["keben:1:1:3", "keben:1:1:4"]     # 原序


def test_pre_sorted_by_conf_desc(env, tmp_path):
    from open_guji_cv.review.cards import cards
    _write_shadow(tmp_path, {"keben:1:1:3": {"char": "天", "conf": 0.91},
                             "keben:1:1:4": {"char": "地", "conf": 0.98}})
    d = cards("keben", "1", 30, "review", env, cls="replace_align", cls_sub="grid", **KW)
    assert [c["id"] for c in d["cards"]] == ["keben:1:1:4", "keben:1:1:3"]


def test_shadow_off_restores_order_and_drops_field(env, tmp_path):
    from open_guji_cv.review.cards import cards
    _write_shadow(tmp_path, {"keben:1:1:4": {"char": "地", "conf": 0.95}})
    d = cards("keben", "1", 30, "review", env, cls="replace_align", cls_sub="grid", shadow=False, **KW)
    assert [c["id"] for c in d["cards"]] == ["keben:1:1:3", "keben:1:1:4"]
    assert all("shadow" not in c for c in d["cards"])
    assert d["shadow_info"]["available"] is True        # 开关关了，文件还在——复选框仍可勾回来


def test_route_shadow_cache_key(client, tmp_path):
    q = ("/api/review/cards?book=keben&pages=1&gate_cut=false&skip_decided=false"
         "&cls=replace_align&cls_sub=grid")
    a = client.get(q).json()
    assert a["shadow_info"]["available"] is False
    _write_shadow(tmp_path, {"keben:1:1:4": {"char": "地", "conf": 0.95}})
    b = client.get(q).json()                             # 文件出现 → 指纹进键，不吃旧缓存
    assert [c["id"] for c in b["cards"]] == ["keben:1:1:4", "keben:1:1:3"]
    off = client.get(q + "&shadow=false").json()          # 关掉 → 另一个键
    assert [c["id"] for c in off["cards"]] == ["keben:1:1:3", "keben:1:1:4"]
    assert "shadow" not in off["cards"][0]


@needs_node
def test_ts_grid_rows_shadow_preselect_field(tmp_path):
    out = _run_ts(tmp_path, """
const cards = [{ id: 'a', ref: { char: '天' }, shadow: { pre: true } },
               { id: 'b', ref: { char: '地' }, shadow: { pre: false } },
               { id: 'c', ref: { char: '玄' } }]
const states = { a: 'skip' }                     // 预勾的被人点掉了
const plain = R.gridRows(cards, states, 1, 2)
const on = R.gridRows(cards, states, 1, 2, undefined, true)
const off = R.gridRows(cards, states, 1, 2, undefined, false)
console.log(JSON.stringify({ plain, on, off, n: R.countShadowPre(cards) }))
""")
    assert all("shadow_preselect" not in r for r in out["plain"])           # 旧调用逐字节不变
    strip = lambda rows: [{k: v for k, v in r.items() if k != "shadow_preselect"} for r in rows]
    assert strip(out["on"]) == out["plain"] == strip(out["off"])
    assert [(r["id"], r["v"], r["shadow_preselect"]) for r in out["on"]] == \
        [("a", "skip", True), ("b", "confirm", False), ("c", "confirm", False)]
    assert all(r["shadow_preselect"] is False for r in out["off"])
    assert out["n"] == 1


def test_export_script(tmp_path):
    import importlib.util
    from pathlib import Path
    sp = Path(__file__).resolve().parents[1] / "scripts/experiments/shadow_admit/export_for_cards.py"
    spec = importlib.util.spec_from_file_location("export_for_cards", sp)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    src = tmp_path / "shadow_picks.jsonl"
    src.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
        {"id": "vol03:1:2:3", "pick": "之", "conf": 0.973412, "cur": "之", "labeled": False},
        {"id": "vol03:1:2:4", "pick": "", "conf": 0.5},
    ]) + "\n", encoding="utf-8")
    doc = m.convert(src, "vol03")
    assert doc == {"version": 1, "book": "vol03", "cells": {"vol03:1:2:3": {"char": "之", "conf": 0.9734}}}
