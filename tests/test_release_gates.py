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


def test_fallback_names_pages_with_many_loose_columns(tmp_path, monkeypatch):
    """一页 ≥3 列没交代 → 点名整页（列错位、卷端页那种整页坏的，逐列交代是白费）；已交代的不算。"""
    st = ProductStore(tmp_path / "products")
    _align(st, 55, {str(c): "x" for c in (1, 2, 3, 4)})
    _align(st, 56, {"1": "x", "2": "y"})
    _align(st, 57, {"1": "x", "2": "y", "3": "z"})
    lists = tmp_path / "lists"
    _tsv(RG.ledger_path("vol01", lists), "页\t列\t处理\t说明", ["57\t3\t改字\t异文"])
    r = RG.check_fallback("vol01", [55, 56, 57], st, lists)
    assert r["hot_pages"] == [{"page": 55, "cols": 4}]      # 57 交代掉一列，只剩两列
    monkeypatch.setattr(RG, "lists_dir", lambda: lists)
    f = CC._fallback("vol01", [55, 56, 57], st)
    assert f["status"] == CC.FAIL and "宜整页进重切清单（p55）" in f["detail"]
    assert f["data"]["hot_pages"] == [{"page": 55, "cols": 4}]


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
    assert "只认重切清单" in c["detail"]                # 中心库待审单不在：只认重切清单
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
    assert root.parse_args(["close-check", "b", "-w", "/x", "--pending"]).pending == ""   # 只写 --pending：读中心库
    assert root.parse_args(["close-check", "b", "-w", "/x", "--pending", "vol04"]).pending == "vol04"


# ── 待审单改读中心库（GUJI-711）──

def _pend(p, cells):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"cells": [{"cell": c, "review": "pending"} for c in cells]}), encoding="utf-8")
    return p


def test_resolve_pending_defaults_to_central(tmp_path, monkeypatch):
    lists = tmp_path / "lists"
    monkeypatch.setattr(RG, "lists_dir", lambda: lists)
    monkeypatch.setattr(RG, "book_text_id", lambda b: "bk01" if b.startswith("vol") else None)
    want = lists / "proofing" / "bk01" / "004.pending.json"
    assert RG.default_pending("vol04") == want
    assert RG.default_pending("vol04", "007") == lists / "proofing" / "bk01" / "007.pending.json"
    assert RG.default_pending("zhiming") is None                       # 推不出章号

    got, note = RG.resolve_pending(None, "vol04")                       # 不在：只认重切清单，说清去哪找
    assert got is None and str(want) in note and "guji db sync" in note
    _pend(want, ["9:1:2"])
    for arg in (None, "", "vol04", "004", "bk01/004", str(want)):
        got, _ = RG.resolve_pending(arg, "vol04")
        assert got == want, arg
    other = _pend(lists / "proofing" / "bk01" / "005.pending.json", [])
    assert RG.resolve_pending("vol05", "vol04")[0] == other              # 给册：那一册的
    assert RG.resolve_pending(None, "vol04", "005")[0] == other          # --chapter 优先


def test_resolve_pending_book_id_by_glob(tmp_path, monkeypatch):
    """meta 里查不到书 id：在 proofing/*/ 下找这一章，恰好一份才用。"""
    lists = tmp_path / "lists"
    monkeypatch.setattr(RG, "lists_dir", lambda: lists)
    monkeypatch.setattr(RG, "book_text_id", lambda b: None)
    a = _pend(lists / "proofing" / "x" / "002.pending.json", [])
    assert RG.resolve_pending(None, "vol02")[0] == a
    _pend(lists / "proofing" / "y" / "002.pending.json", [])
    got, note = RG.resolve_pending(None, "vol02")
    assert got is None and "推不出" in note


def test_resolve_pending_old_book_text_path(tmp_path, monkeypatch):
    """给了 book-text 的旧路径、文件不在：提示已迁中心库并指出新路径；新路径在就改读它。"""
    lists = tmp_path / "lists"
    monkeypatch.setattr(RG, "lists_dir", lambda: lists)
    monkeypatch.setattr(RG, "book_text_id", lambda b: None)
    old = tmp_path / "book-text" / "Book" / "g" / "z" / "k" / "bk01" / "004.pending.json"
    new = lists / "proofing" / "bk01" / "004.pending.json"
    got, note = RG.resolve_pending(str(old), "vol04")
    assert got is None and "已从 book-text 迁到中心库" in note and str(new) in note
    _pend(new, ["9:1:2"])
    got, note = RG.resolve_pending(str(old), "vol04")
    assert got == new and "改读这份" in note
    _pend(old, [])                                                      # 旧文件真在：照给的用
    assert RG.resolve_pending(str(old), "vol04") == (old, "")


def test_close_check_2c_reads_central_pending(tmp_path, monkeypatch):
    exp = tmp_path / "exp"
    exp.mkdir()
    _export(exp, "甲□", ["9:1:1", "9:1:2"])                              # 章号 001 从 001.lines.md 取
    lists = tmp_path / "lists"
    monkeypatch.setattr(RG, "lists_dir", lambda: lists)
    monkeypatch.setattr(RG, "book_text_id", lambda b: "bk01")
    assert CC._lacuna("zhiming", exp, None, None)["status"] == CC.FAIL
    p = _pend(lists / "proofing" / "bk01" / "001.pending.json", ["9:1:2"])
    c = CC._lacuna("zhiming", exp, None, None)
    assert c["status"] == CC.PASS and str(p) in c["detail"]


def test_close_check_1c_models(monkeypatch, tmp_path):
    """1c：本机缺 torch／权重，或 Step5-b 产物没出 embedding 候选 → FAIL（D 10-19 报：没 torch 跑的产物 1a 照报新鲜）。"""
    import importlib.util
    import types
    from open_guji_cv.clustering import cnn_candidates as CNN
    from open_guji_cv.products.kinds.recog import ColumnRare, PageRare, RareRec
    from open_guji_cv.seg import cut_select
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


def test_cli_has_strict_cv_option():
    import argparse
    from open_guji_cv import cli_v2
    root = argparse.ArgumentParser()
    cli_v2.register_subcommands(root.add_subparsers(dest="command"))
    assert root.parse_args(["close-check", "b", "-w", "/x", "--strict-cv"]).strict_cv is True
    assert root.parse_args(["close-check", "b", "-w", "/x"]).strict_cv is False
