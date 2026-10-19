# -*- coding: utf-8 -*-
"""放行硬项 2c（□ 有去向）、2d（整理本对不上的列有交代）：GUJI-624，用户 10-19 定。数据全在 tmp 里现造。"""
from __future__ import annotations

import json

from open_guji_cv.core.spec import page_key
from open_guji_cv.ops import close_check as CC
from open_guji_cv.ops import release_gates as RG
from open_guji_cv.products.kinds.recog import PageAlignRef
from open_guji_cv.products.store import ProductStore


def _export(d, chars: str, anchors: list[str | None]):
    (d / "001.lines.md").write_text("<!-- p1 -->\n" + chars + "\n", encoding="utf-8")
    cells = [{"a": a, "o": i, "c": ch} for i, (ch, a) in enumerate(zip(chars, anchors)) if a]
    (d / "001.pages.json").write_text(json.dumps({"pages": [{"cells": cells}]}), encoding="utf-8")


def _tsv(p, header: str, rows: list[str]):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# 注释行\n" + header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def test_lacuna_needs_pending_or_recut(tmp_path):
    exp = tmp_path / "exp"
    exp.mkdir()
    _export(exp, "甲□乙□丙□〓", ["9:1:1", "9:1:2", "9:1:3", "90:1:3a", "89:7:1", "89:8:2", None])
    pend = tmp_path / "001.pending.json"
    pend.write_text(json.dumps({"cells": [{"cell": "9:1:2", "review": "pending"},
                                          {"cell": "90:1:3a", "review": "human"}]}), encoding="utf-8")
    lists = tmp_path / "lists"
    _tsv(RG.recut_path("vol01", lists), "位置\t原因", ["89:8\t职名页错切", "坏位置\tx"])
    r = RG.check_lacuna("vol01", exp, None, pend, lists)
    assert r["lacuna"] == 4
    assert r["pending"] == ["9:1:2", "90:1:3a"]     # 人在审页上裁定保持 □ 的（review=human）也算
    assert r["recut"] == ["89:8:2"]
    assert r["loose"] == ["偏移6"]                   # 没格的占位算没去向
    assert r["recut_bad"] == ["坏位置"]


def test_recut_list_granularity(tmp_path):
    rl = RG.RecutList([["89"], ["90:2"], ["101:2:3"], ["105:1:2a"]])
    assert rl.covers_cell("89:7:16") and rl.covers_col(89, 3)
    assert rl.covers_cell("90:2:5") and not rl.covers_cell("90:3:5")
    assert rl.covers_cell("101:2:3") and not rl.covers_cell("101:2:4")
    assert rl.covers_cell("105:1:2a") and not rl.covers_col(105, 1)


def _align(st, page: int, fallback: dict[str, str]):
    st.write("vol01", "align_ref", page_key(page),
             {"align_ref": PageAlignRef(page=page, coord_fallback=fallback)})


def test_fallback_columns_need_ledger_or_recut(tmp_path):
    st = ProductStore(tmp_path / "products")
    _align(st, 10, {"7": "格与整理本 3 字对不上", "2": "列行对应不成立"})
    _align(st, 89, {"5": "x", "9": "y"})
    _align(st, 41, {"1": "z"})
    lists = tmp_path / "lists"
    _tsv(RG.recut_path("vol01", lists), "位置\t原因", ["89\t职名页整页重切"])
    _tsv(RG.ledger_path("vol01", lists), "页\t列\t处理\t说明",
         ["10\t7\t改字\t实□古→實考古", "10\t2\t一致\t", "41\t1\t说明\t整理本缺「暘」，刻本不缺"])
    r = RG.check_fallback("vol01", [10, 41, 89, 196], st, lists)
    assert r["columns"] == 5
    assert r["by_action"] == {"改字": 1, "说明": 1, "重切": 2}
    assert r["loose"] == ["10:2"]                     # 「一致」没写说明 → 那一行不算
    assert r["ledger_bad"] == ["10:2 处理是「一致」但没写说明"]


def test_ledger_rejects_unknown_action(tmp_path):
    _tsv(RG.ledger_path("b", tmp_path), "页\t列\t处理\t说明", ["1\t2\t忽略\t", "x\t2\t改字\t"])
    led, bad = RG.load_ledger("b", tmp_path)
    assert led == {} and len(bad) == 2


def test_close_check_items_2c_2d(monkeypatch, tmp_path):
    exp = tmp_path / "exp"
    exp.mkdir()
    _export(exp, "甲□", ["9:1:1", "9:1:2"])
    monkeypatch.setattr(RG, "lists_dir", lambda: tmp_path / "lists")
    st = ProductStore(tmp_path / "products")
    _align(st, 9, {"3": "x"})
    c = CC._lacuna("vol01", exp, None, None)
    assert c["no"] == "2c" and c["status"] == CC.FAIL and c["data"]["loose"] == ["9:1:2"]
    assert "没给 --pending" in c["detail"]
    f = CC._fallback("vol01", [9], st)
    assert f["no"] == "2d" and f["status"] == CC.FAIL and f["data"]["loose"] == ["9:3"]
    _tsv(RG.recut_path("vol01", tmp_path / "lists"), "位置\t原因", ["9\t整页重切"])
    assert CC._lacuna("vol01", exp, None, None)["status"] == CC.PASS
    assert CC._fallback("vol01", [9], st)["status"] == CC.PASS


def test_cli_has_pending_option():
    import argparse
    from open_guji_cv import cli_v2
    root = argparse.ArgumentParser()
    cli_v2.register_subcommands(root.add_subparsers(dest="command"))
    assert root.parse_args(["close-check", "b", "-w", "/x", "--pending", "x.json"]).pending == "x.json"
    assert root.parse_args(["close-check", "b", "-w", "/x"]).pending is None
