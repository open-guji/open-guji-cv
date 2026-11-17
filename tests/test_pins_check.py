"""推钉子预检（`feedback/pins_check.py`，A22 F3）：纯函数部分，数据自造。"""
from types import SimpleNamespace

from open_guji_cv.eval import seg_screen as ss
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


def test_split_preexisting():
    from open_guji_cv.feedback.pins_check import split_preexisting
    old = {"a": {"status": "unanchored"}, "b": {"status": "valid", "bound": "k"},
           "c": {"status": "review"}}
    probs, pre = split_preexisting(["a", "b", "c", "d"], {"c"}, old)
    # a：不在改动列、旧下也没绑上 → 老失锚；b：旧下绑得上 → 本次弄坏的；c：在改动列；d：没有旧切分
    assert pre == {"a"} and probs == ["b", "c", "d"]


def test_duplicate_anchor_keys():
    import json
    from open_guji_cv.feedback.pins_check import duplicate_anchor_keys
    ln = [json.dumps({"event": "e1", "key": "b:1:2:3"}), "", json.dumps({"event": "e1", "key": "b:1:2:3"}),
          json.dumps({"event": "e1", "key": "b:1:2:4"}), json.dumps({"event": "e2", "key": "b:1:2:3"})]
    assert duplicate_anchor_keys(ln) == {("e1", "b:1:2:3"): 2}


def test_merge_anchor_drafts_replaces_in_place():
    import json
    from open_guji_cv.feedback.pins_check import duplicate_anchor_keys, merge_anchor_drafts
    cur = [json.dumps({"event": "e1", "key": "k1", "anchor": {"bbox": [0]}}),
           json.dumps({"event": "e2", "key": "k2", "anchor": {"bbox": [1]}}),
           json.dumps({"event": "e1", "key": "k1", "anchor": {"bbox": [2]}})]
    drafts = [{"event": "e1", "key": "k1", "anchor": {"ink_bbox": [9]}},
              {"event": "e3", "key": "k3", "anchor": {"ink_bbox": [8]}}]
    out, rep = merge_anchor_drafts(cur, drafts)
    rows = [json.loads(x) for x in out]
    assert rep == {"e1"}
    assert [r["event"] for r in rows] == ["e1", "e2", "e3"]
    assert rows[0]["anchor"] == {"ink_bbox": [9]}
    assert duplicate_anchor_keys(out) == {}


def _geo_col(cells):
    recs = [CellRec(slot=s, pos=s, y0=y0, y1=y1, x0=0, x1=100, kind="char", order=i)
            for i, (s, y0, y1) in enumerate(cells)]
    return ColumnCells(col=1, ok=True, n_body_slots=len(recs), cells=recs, period=100.0, content_x=(0.0, 100.0),
                       border_top=20.0, border_bottom=500.0, flags=["manual_cells"])


def test_pin_geometry_two_chars_and_ink():
    import numpy as np
    g = np.full((500, 100), 255, np.uint8)
    g[110:190, 30:70] = 0
    g[210:290, 30:70] = 0                     # 钉子把两个字钉进一格（100–300）
    g[320:390, 30:70] = 0
    g[320:436, 40:50] = 0                     # 下一格字竖笔尾被 400 处的格线劈了
    g[440:490, 30:70] = 0
    cc = _geo_col([(1, 100, 300), (2, 300, 400), (3, 400, 500)])
    out = ss.pin_geometry(g, cc, 100.0)
    kinds = {(t["kind"], t["slot"]) for t in out}
    assert ("two", "1") in kinds and ("ink", "2|3") in kinds
    two = next(t for t in out if t["kind"] == "two")
    ink = next(t for t in out if t["kind"] == "ink")
    assert two["block"] and not ink["block"]          # 没裁判：压墨只当提示

    class J:
        def assess(self, *a, **k):
            return [0.9, 0.99], [0, 0]
    ink_j = next(t for t in ss.pin_geometry(g, cc, 100.0, judge=J()) if t["kind"] == "ink")
    assert ink_j["block"] and ink_j["level"] == "中"


def test_pin_geometry_clean_column():
    import numpy as np
    g = np.full((400, 100), 255, np.uint8)
    for y in (110, 210, 310):
        g[y:y + 80, 30:70] = 0
    assert ss.pin_geometry(g, _geo_col([(1, 100, 200), (2, 200, 300), (3, 300, 400)]), 100.0) == []


# ── 1c. 整列丢字（SJ r75） ──────────────────────────────────────────────────

def _col(rows, period=100.0, bt=None, bb=None, quad=None):
    """rows: [(slot, sub, kind, y0, y1)]，列宽 100。"""
    cells = [CellRec(slot=s, pos=i + 1, y0=y0, y1=y1, x0=0, x1=100, kind=k, sub=sub, order=i,
                     quad_page=quad(y0, y1) if quad else None)
             for i, (s, sub, k, y0, y1) in enumerate(rows)]
    return ColumnCells(col=3, ok=True, n_body_slots=len(rows), period=period, content_x=(0, 100),
                       border_top=bt, border_bottom=bb, cells=cells)


def test_pin_notes():
    it = _item("28", 93, 3, PIN)
    it["expected"]["count_why"] = "原列挤格，22 格"
    assert pc.pin_notes([it, _item("28", 93, 4, PIN)], "28") == {(93, 3): "原列挤格，22 格"}


def test_check_pin_count():
    old = _col([(s, None, "char", (s - 1) * 100, s * 100) for s in range(1, 22)]
               + [(22, None, "blank", 2100, 2200)])
    full = [{"slot": s, "kind": "char", "y0": 0, "y1": 1, "x0": 0, "x1": 1} for s in range(1, 22)]
    assert pc.check_pin_count(full, old) is None                       # 21 格对 21 个有字格（blank 不算）
    r = pc.check_pin_count(full[:3], old)
    assert r["block"] and r["new"] == 3 and r["old"] == 21 and "count_why" in r["note"]
    r = pc.check_pin_count(full[:3], old, why="后 18 格是空白")
    assert not r["block"] and "后 18 格是空白" in r["note"]
    # 旧切分没有这一列：比旧钉子
    assert pc.check_pin_count(full[:3], None, old_pin=full[:3]) is None
    assert pc.check_pin_count(full[:3], None, old_pin=full)["block"]
    r = pc.check_pin_count(full[:3], None)
    assert not r["block"] and r["old"] is None


def _gray(h=2200, blocks=()):
    import numpy as np
    g = np.full((h, 100), 255, np.uint8)
    for y0, y1 in blocks:
        g[y0:y1, 30:70] = 0
    return g


def test_uncovered_ink_lost_column():
    # 21 个字，钉子只写了前 3 格：其余 18 个字都在格外
    chars = [(s * 100 + 10, s * 100 + 90) for s in range(21)]
    pin = _col([(s + 1, None, "char", s * 100, s * 100 + 100) for s in range(3)])
    segs = pc.uncovered_ink(_gray(blocks=chars), pin, 100)
    assert len(segs) == 18 and segs[0]["y0"] == 310 and not any(u["seal"] for u in segs)
    # 整列钉全：没有格外墨
    full = _col([(s + 1, None, "char", s * 100, s * 100 + 100) for s in range(21)])
    assert pc.uncovered_ink(_gray(blocks=chars), full, 100) == []


def test_uncovered_ink_exemptions():
    import numpy as np
    pin = _col([(1, None, "char", 100, 200)], bt=50, bb=2150)
    g = _gray(blocks=[(110, 190)])
    g[45:56, :] = 0                       # 上版框横线（长直线剥掉）
    g[2140:2160, 40:60] = 0               # 贴下版框线的残墨（列端框线）
    g[300:315, 40:60] = 0                 # 15px 的点，不够 25px
    g[:, 98:100] = 0                      # 界行（竖长直线剥掉）
    assert pc.uncovered_ink(g, pin, 100) == []
    g[500:560, 30:70] = 0                 # 一个漏掉的字
    segs = pc.uncovered_ink(g, pin, 100)
    assert [(u["y0"], u["y1"]) for u in segs] == [(500, 560)]
    # 压着印章：照报，但标 seal
    segs = pc.uncovered_ink(g, pin, 100, seal_spans=[(480, 600)])
    assert segs[0]["seal"]
    # 高分辨率：门槛随字高放大（参照字高 200 → 50px），40px 的段不报
    g2 = _gray(blocks=[(110, 190), (500, 540)])
    assert pc.uncovered_ink(g2, pin, 200) == []
    assert np.asarray(g2).shape == (2200, 100)


def test_seal_spans_col():
    from open_guji_cv.products.kinds.seals import Seal

    def quad(y0, y1):                     # 列图 y → 页 y = 2y + 100；列占页 x 1000–1100
        return [(1000, 2 * y0 + 100), (1100, 2 * y0 + 100), (1100, 2 * y1 + 100), (1000, 2 * y1 + 100)]
    col = _col([(1, None, "char", 0, 100), (2, None, "char", 100, 200)], quad=quad)
    hit = Seal(kind="crisp", bbox=(1050, 300, 1300, 500), score=1, source="template")
    miss = Seal(kind="crisp", bbox=(0, 300, 500, 500), score=1, source="template")
    spans = pc.seal_spans_col(col, [hit, miss])
    assert len(spans) == 1 and abs(spans[0][0] - 100) < 1e-6 and abs(spans[0][1] - 200) < 1e-6
    assert pc.seal_spans_col(col, []) == []
    assert pc.seal_spans_col(_col([(1, None, "char", 0, 100)]), [hit]) == [(float("-inf"), float("inf"))]
