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


def test_close_check_1c_models(monkeypatch, tmp_path):
    """1c：本机缺 torch／权重，或 Step5-b 产物没出 embedding 候选 → FAIL（D 10-19 报：没 torch 跑的产物 1a 照报新鲜）。"""
    import importlib.util
    import types
    from open_guji_cv.clustering import cnn_candidates as CNN
    from open_guji_cv.products.kinds.recog import ColumnRare, PageRare, RareRec
    from open_guji_cv.utils import cut_select
    w1, w2 = tmp_path / "judge.pt", tmp_path / "cnn.pt"
    w1.write_bytes(b"x")
    w2.write_bytes(b"x")
    monkeypatch.setattr(cut_select, "DEFAULT_CKPT", w1)
    monkeypatch.setattr(CNN, "DEFAULT_CKPT", w2)
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda n, *a: object() if n == "torch" else real(n, *a))
    st = ProductStore(tmp_path / "products")
    eng = types.SimpleNamespace(store=st, book=types.SimpleNamespace(id="vol01"))

    def rare(page, sources, n=1):
        st.write("vol01", "rare_candidates", page_key(page), {"rare_candidates": PageRare(
            page=page, sources=sources, columns=[ColumnRare(col=1, chars=[RareRec(id=f"r{i}", slot=i) for i in range(n)])])})

    rare(1, {"emb": 5, "cnn": 1})
    rare(2, {}, n=0)                                  # 这页没有生僻字要查：不算
    assert CC._models(eng, [1, 2, 3])["status"] == CC.PASS
    rare(3, {"cnn": 4})
    r = CC._models(eng, [1, 2, 3])
    assert r["status"] == CC.FAIL and r["data"]["rare_no_emb"] == [3]
    monkeypatch.setattr(importlib.util, "find_spec", lambda n, *a: None if n == "torch" else real(n, *a))
    w1.unlink()
    r = CC._models(eng, [1])
    assert r["status"] == CC.FAIL and r["data"]["env"][0] == "没装 torch" and len(r["data"]["env"]) == 2
