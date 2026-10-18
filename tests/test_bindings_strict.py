# -*- coding: utf-8 -*-
"""R1/R3 严格绑定（`GUJI_BINDINGS_STRICT`，缺省关；GUJI-555）。"""
from __future__ import annotations

from types import SimpleNamespace as NS

import open_guji_cv.feedback.bindings as B
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
from open_guji_cv.feedback.lookup import human_chars


def _ev(key, shape, seq, ts):
    _, pg, col, slot = key.split(":")
    e = make_event("b", seq, "confirm",
                   EventTarget(step="seed_admit", unit="cell", key=key, book="vol02",
                               page=int(pg), col=int(col), slot=int(slot)),
                   {"v": "confirm", "shape": shape}, source_format="server")
    e.ts = ts
    return e


def _bound(events, mapping):
    """mapping: {event_id: (status, bound)}"""
    return {e.id: {"event": e.id, "key": e.target.key, "ts": e.ts, "bound": mapping[e.id][1],
                   "status": mapping[e.id][0]} for e in events}


def _cells(boxes):
    cols = {}
    for (col, slot), (x0, y0, x1, y1) in boxes.items():
        q = [(x1, y0), (x0, y0), (x0, y1), (x1, y1)]
        cols.setdefault(col, []).append(NS(slot=slot, sub=None, kind="char", quad_page=q))
    return NS(columns=[NS(col=c, cells=cs) for c, cs in cols.items()])


def _hc(monkeypatch, tmp_path, evs, mapping, strict):
    log = EventLog(tmp_path)
    log.append(evs)
    monkeypatch.setattr(B, "book_bindings", lambda *a, **k: _bound(evs, mapping))
    if strict:
        monkeypatch.setenv("GUJI_BINDINGS_STRICT", "1")
    else:
        monkeypatch.delenv("GUJI_BINDINGS_STRICT", raising=False)
    return human_chars("vol02", log, stale={}, bind=True)


def test_r1_unusable_newer_event_does_not_let_older_win(monkeypatch, tmp_path):
    old = _ev("vol02:110:3:12", "愚", 1, "2026-09-08T00:00:00Z")
    new = _ev("vol02:110:3:12", "也", 2, "2026-10-02T01:21:49Z")
    m = {old.id: ("valid", "vol02:110:3:12"), new.id: ("unanchored", None)}
    assert _hc(monkeypatch, tmp_path, [old, new], m, strict=False) == {"vol02:110:3:12": "愚"}
    assert _hc(monkeypatch, tmp_path / "s", [old, new], m, strict=True) == {}


def test_r1_usable_newer_event_still_wins(monkeypatch, tmp_path):
    old = _ev("vol02:110:3:12", "愚", 1, "2026-09-08T00:00:00Z")
    new = _ev("vol02:110:3:12", "也", 2, "2026-10-02T01:21:49Z")
    m = {old.id: ("valid", "vol02:110:3:12"), new.id: ("valid", "vol02:110:3:12")}
    assert _hc(monkeypatch, tmp_path, [old, new], m, strict=True) == {"vol02:110:3:12": "也"}


def test_r1_rebound_yields_to_later_native_event_on_target(monkeypatch, tmp_path):
    old = _ev("vol02:188:7:4", "主", 1, "2026-09-08T00:00:00Z")      # 老裁 rebound 到 7:5
    own = _ev("vol02:188:7:5", "云", 2, "2026-10-02T00:00:00Z")      # 7:5 自己更晚的裁决，不可用
    m = {old.id: ("rebound", "vol02:188:7:5"), own.id: ("unanchored", None)}
    assert _hc(monkeypatch, tmp_path, [old, own], m, strict=False) == {"vol02:188:7:5": "主"}
    assert _hc(monkeypatch, tmp_path / "s", [old, own], m, strict=True) == {}


def test_r3_rebound_with_ctx_differ_goes_to_review(monkeypatch):
    cur = _cells({(4, 20): (0, 300, 100, 400), (4, 21): (0, 400, 100, 500)})
    monkeypatch.setattr(B, "_cells_versions", lambda *a, **k: [("current", B._ts("2026-09-25T00:00:00Z"), float("inf"), cur)])
    monkeypatch.setattr(B, "load_backfill_ctx", lambda book: {}, raising=False)
    import open_guji_cv.feedback.anchor_backfill as AB
    monkeypatch.setattr(AB, "load_backfill_ctx", lambda book: {"e1": "differ"})
    ev = _ev("vol02:75:4:21", "目", 1, "2026-09-08T00:00:00Z")
    ev.id = "e1"
    bf = {"e1": {"ink_bbox": [0, 305, 100, 395], "source": "backfill:ink"}}
    kw = dict(store=object(), cache=NS(get=lambda *a, **k: None), glyph_db=None, backfill=bf)
    monkeypatch.delenv("GUJI_BINDINGS_STRICT", raising=False)
    assert B.compute_page("vol02", 75, [ev], **kw)[0]["status"] == "rebound"
    monkeypatch.setenv("GUJI_BINDINGS_STRICT", "1")
    r = B.compute_page("vol02", 75, [ev], **kw)[0]
    assert r["status"] == "review" and r["why"] == "rebound_ctx_differ"


def test_r3_column_shift_without_ctx_support_goes_to_review():
    def row(slot, ctx):
        return {"key": f"vol02:75:1:{slot}", "bound": f"vol02:75:1:{slot - 1}", "status": "rebound", "ctx": ctx}
    rows = [row(5, "variant"), row(6, "variant"), row(7, "variant")]
    B._col_shift_gate(rows)
    assert {r["status"] for r in rows} == {"review"}
    rows = [row(5, "equal"), row(6, "equal"), row(7, "variant")]
    B._col_shift_gate(rows)
    assert {r["status"] for r in rows} == {"rebound"}
    rows = [{"key": "vol02:75:1:5", "bound": "vol02:75:1:4", "status": "rebound"}] * 3   # 无 ctx 记录：不参与
    B._col_shift_gate(rows)
    assert {r["status"] for r in rows} == {"rebound"}
