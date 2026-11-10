"""推钉子预检（`feedback/pins_check.py`，A22 F3）：纯函数部分，数据自造。"""
from types import SimpleNamespace

from open_guji_cv.feedback import pins_check as pc
from open_guji_cv.products.kinds.cells import CellRec, ColumnCells, PageCells
from open_guji_cv.products.kinds.chars import CharRec, ColumnChars


def _item(book, page, col, cells, status="active"):
    return {"anchor": {"book": book, "page": page, "col": col}, "expected": {"cells": cells}, "status": status}


PIN = [{"slot": 1, "sub": "a", "kind": "jiazhu_a", "y0": 0, "y1": 40, "x0": 60, "x1": 100},
       {"slot": 1, "sub": "b", "kind": "jiazhu_b", "y0": 0, "y1": 40, "x0": 0, "x1": 60},
       {"slot": 2, "sub": None, "kind": "char", "y0": 40, "y1": 120, "x0": 0, "x1": 100}]


def test_pins_of_filters_book_and_status():
    items = [_item("04", 3, 2, PIN), _item("05", 3, 2, PIN), _item("04", 4, 1, PIN, status="retired"),
             _item("04", 5, 1, [])]
    assert list(pc.pins_of(items, "04")) == [(3, 2)]


def test_diff_pins():
    old = {(1, 1): PIN, (1, 2): PIN, (2, 1): PIN}
    moved = [dict(c) for c in PIN]
    moved[2]["y1"] = 130
    new = {(1, 1): list(reversed(PIN)), (1, 2): moved, (3, 1): PIN}
    assert pc.diff_pins(old, new) == {(1, 2): "changed", (2, 1): "removed", (3, 1): "added"}


def _ch(slot, sub=None, typ="char"):
    return CharRec(id=f"b:1:1:{slot}{sub or ''}", slot=slot, pos=slot, idx=slot - 1, sub=sub, cell_type=typ,
                   bbox_col=(0, 0, 1, 1))


def test_pin_vs_chars_ok_and_problems():
    good = ColumnChars(col=2, ok=True, chars=[_ch(1, "a"), _ch(1, "b"), _ch(2)])
    assert pc.check_pin_vs_chars(PIN, good) == []
    lost = ColumnChars(col=2, ok=True, chars=[_ch(1, "a"), _ch(1, "b", "empty"), _ch(3)])
    probs = pc.check_pin_vs_chars(PIN, lost)
    assert any("1b" in p and "空格" in p for p in probs)
    assert any("2" in p and "没有这一格" in p for p in probs)
    assert any("多出字格 3" in p for p in probs)
    assert pc.check_pin_vs_chars(PIN, None) == ["cell_shrink 没有这一列"]


def test_classify_row():
    assert pc.classify_row({"status": "rebound", "bound": "x"}) == "ok"
    assert pc.classify_row({"status": "unanchored", "bound": "x"}) == "ok"
    assert pc.classify_row({"status": "unanchored", "bound": None, "why": "no_patch"}) == "unbound"
    assert pc.classify_row({"status": "unanchored", "bound": None}) == "unbound"
    assert pc.classify_row({"status": "review"}) == "lost"


def _cells(page, rows):
    """rows: [(col, slot, sub, (x0, y0, x1, y1) 页面框)]，quad 用四角。"""
    cols = {}
    for col, slot, sub, (x0, y0, x1, y1) in rows:
        cols.setdefault(col, []).append(CellRec(
            slot=slot, pos=slot, y0=y0, y1=y1, x0=0, x1=1, kind="char", sub=sub, order=len(cols.get(col, [])),
            quad_page=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]))
    return PageCells(page=page, period=100.0, ref_w=200.0, columns=[
        ColumnCells(col=c, ok=True, n_body_slots=len(v), cells=v) for c, v in cols.items()])


def test_propose_anchor_rebound_after_shift():
    old = _cells(7, [(1, 1, None, (0, 0, 100, 100)), (1, 2, None, (0, 100, 100, 200))])
    # 新切分列首多出一格：旧 1 号那块墨现在是 2 号
    new = _cells(7, [(1, 1, None, (0, -60, 100, 0)), (1, 2, None, (0, 0, 100, 100)), (1, 3, None, (0, 100, 100, 200))])
    d = pc.propose_anchor("b:7:1:1", "evt1", pc.cell_boxes(old), new)
    assert d["anchor"]["source"] == "backfill:ink" and d["anchor"]["ink_bbox"] == [0, 0, 100, 100]
    assert d["evidence"]["pred"] == "rebound" and d["evidence"]["to"] == "b:7:1:2"


def test_propose_anchor_split_is_review_and_missing_is_none():
    old = _cells(7, [(1, 1, None, (0, 0, 100, 100))])
    new = _cells(7, [(1, 1, None, (0, 0, 100, 50)), (1, 2, None, (0, 50, 100, 100))])
    assert pc.propose_anchor("b:7:1:1", "e", pc.cell_boxes(old), new)["evidence"]["pred"] == "review"
    assert pc.propose_anchor("b:7:1:9", "e", pc.cell_boxes(old), new) is None


def test_duplicate_event_ids():
    evs = [SimpleNamespace(id="a"), SimpleNamespace(id="b"), SimpleNamespace(id="a"), {"id": "b"}, {"id": "c"}]
    assert pc.duplicate_event_ids(evs) == {"a": 2, "b": 2}


def test_executor_like_restores_env(tmp_path, monkeypatch):
    import os

    from open_guji_cv.feedback import bindings
    monkeypatch.setenv("GUJI_CACHE_DIR", "/keep")
    monkeypatch.delenv("GUJI_BINDINGS_NO_RENDER", raising=False)
    before = bindings._bindings_dir
    with pc.executor_like(tmp_path):
        assert os.environ["GUJI_BINDINGS_NO_RENDER"] == "1"
        assert bindings._bindings_dir("04") == tmp_path / "bindings" / "04"
    assert os.environ["GUJI_CACHE_DIR"] == "/keep" and "GUJI_BINDINGS_NO_RENDER" not in os.environ
    assert bindings._bindings_dir is before


def test_retire_verdict():
    pin = [{"slot": 1, "sub": None, "y0": 0, "y1": 100}, {"slot": 2, "sub": None, "y0": 100, "y1": 200}]
    def col(edges, kinds=("char", "char")):
        return ColumnCells(col=1, ok=True, n_body_slots=2, period=100.0, cells=[
            CellRec(slot=i + 1, pos=i + 1, y0=a, y1=b, x0=0, x1=1, kind=k, order=i)
            for i, ((a, b), k) in enumerate(zip(edges, kinds))])
    assert pc.retire_verdict(pin, col([(2, 98), (98, 203)]))["verdict"] == "retire"
    assert pc.retire_verdict(pin, col([(0, 120), (120, 200)]))["verdict"] == "near"
    assert pc.retire_verdict(pin, col([(0, 150), (150, 200)]))["verdict"] == "keep"
    r = pc.retire_verdict(pin, col([(0, 100), (100, 200)], kinds=("char", "blank")))
    assert r["verdict"] == "keep" and "缺 1 格" in r["why"]


def test_propose_anchor_uses_old_bound_cell():
    # 旧切分里人裁当时绑在 2 号（格号已挪），事件键还是 1 号：墨框要取 2 号那格（SJ 01:49:4 務→府）
    old = _cells(7, [(1, 1, None, (0, 0, 100, 100)), (1, 2, None, (0, 100, 100, 200))])
    new = _cells(7, [(1, 1, None, (0, 100, 100, 200))])
    d = pc.propose_anchor("b:7:1:1", "e", pc.cell_boxes(old), new, old_bound="b:7:1:2")
    assert d["anchor"]["ink_bbox"] == [0, 100, 100, 200]
    assert d["evidence"]["old_cell"] == "b:7:1:2" and d["evidence"]["to"] == "b:7:1:1"


def test_run_failures():
    from open_guji_cv.core.engine import PageOutcome
    rep = SimpleNamespace(outcomes=[PageOutcome("row_segment", 3, "ok"),
                                    PageOutcome("cell_shrink", 3, "failed", error="上游缺失")])
    assert pc.run_failures(rep) == ["cell_shrink:p3 上游缺失"]
    assert pc.run_failures(None) == []


def test_drop_rerun_products(tmp_path):
    d = tmp_path / "b" / "cell_shrink"
    d.mkdir(parents=True)
    for n in ("p0003.json", "p0004.json", "_manifest.jsonl"):
        (d / n).write_text("{}")
    pc._drop_rerun_products(tmp_path, "b", [3])
    assert sorted(f.name for f in d.iterdir()) == ["_manifest.jsonl", "p0004.json"]


def test_glyph_db_missing(tmp_path, monkeypatch):
    import sqlite3

    from open_guji_cv.core import workspace
    db = tmp_path / "glyph.db"
    monkeypatch.setattr(workspace, "glyph_db_path", lambda *a, **k: db)
    assert "没有" in pc.glyph_db_missing()
    sqlite3.connect(str(db)).close()
    assert "空" in pc.glyph_db_missing()
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE instances (instance_id TEXT)")
    con.commit()
    con.close()
    assert pc.glyph_db_missing() is None


def test_judge_missing(monkeypatch):
    import pytest
    p = SimpleNamespace(cut_judge="unet", judge_fingerprint="")
    ctx = SimpleNamespace(params_for=lambda st: p)
    with pytest.raises(pc.SandboxNotReady):
        pc.judge_missing(ctx)
    p.judge_fingerprint = "abc"
    pc.judge_missing(ctx)
    pc.judge_missing(SimpleNamespace(params_for=lambda st: SimpleNamespace(cut_judge="none", judge_fingerprint="")))


def test_old_char():
    seed = SimpleNamespace(columns=[SimpleNamespace(chars=[SimpleNamespace(id="b:7:1:2", char="務")])])
    assert pc.old_char(seed, "b:7:1:2") == "務" and pc.old_char(seed, "b:7:1:3") is None and pc.old_char(None, "x") is None
