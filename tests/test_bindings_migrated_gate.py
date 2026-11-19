# -*- coding: utf-8 -*-
"""迁移补锚闸（`backfill:migrated`，2026-11-17 ZM 第一册线报）：补锚框与上一版锚落到的现格不同 → 不认。"""
from __future__ import annotations

from types import SimpleNamespace as NS

import open_guji_cv.feedback.bindings as B
from open_guji_cv.feedback.events import EventTarget, make_event


def _cells(boxes):
    cols = {}
    for (col, slot), (x0, y0, x1, y1) in boxes.items():
        q = [(x1, y0), (x0, y0), (x0, y1), (x1, y1)]
        cols.setdefault(col, []).append(NS(slot=slot, sub=None, kind="char", quad_page=q))
    return NS(columns=[NS(col=c, cells=cs) for c, cs in cols.items()])


#: vol02:175 第 1 列：8、9 两格（坐标取自实例，r12g24 包）
CUR = _cells({(1, 8): (69, 862, 252, 979), (1, 9): (69, 979, 252, 1094)})
MIG = {"v": 1, "space": "raw_page_px@top-right", "bbox": [68.79, 862.09, 251.99, 979.18],
       "source": "backfill:migrated"}


def _ev(prev_id="E~q~r"):
    anchor = {"source_rev": "5", "migrated_from": {"id": prev_id, "source_rev": "4"}} if prev_id else None
    e = make_event("b", 1, "confirm",
                   EventTarget(step="seed_admit", unit="cell", key="vol02:175:1:8", book="vol02",
                               page=175, col=1, slot=8, anchor=anchor),
                   {"v": "confirm", "shape": "卷"}, source_format="server")
    e.ts = "2026-09-10T05:28:25Z"
    e.id = "E~q~r~r"
    return e


def _run(monkeypatch, ev, backfill):
    monkeypatch.setattr(B, "_cells_versions",
                        lambda *a, **k: [("current", B._ts("2026-11-17T00:00:00Z"), float("inf"), CUR)])
    monkeypatch.delenv("GUJI_BINDINGS_STRICT", raising=False)
    kw = dict(store=object(), cache=NS(get=lambda *a, **k: None), glyph_db=None, backfill=backfill)
    return B.compute_page("vol02", 175, [ev], **kw)[0]


def test_prev_anchor_on_other_cell_goes_to_review(monkeypatch):
    prev = {"bbox": [84.36, 979.16, 242.67, 1080.98], "source": "migrate:qiefen-v2+rebase-r4"}
    r = _run(monkeypatch, _ev(), {"E~q~r~r": MIG, "E~q~r": prev})
    assert r["status"] == "review" and r["why"] == "migrated_prev_differs"
    assert r["bound"] == "vol02:175:1:8" and r["prev_bound"] == "vol02:175:1:9"


def test_prev_anchor_on_same_cell_stays_valid(monkeypatch):
    prev = {"bbox": [70, 865, 250, 975], "source": "migrate:qiefen-v2+rebase-r4"}
    r = _run(monkeypatch, _ev(), {"E~q~r~r": MIG, "E~q~r": prev})
    assert r["status"] == "valid" and "why" not in r


def test_no_prev_anchor_keeps_old_rule(monkeypatch):
    assert _run(monkeypatch, _ev(), {"E~q~r~r": MIG})["status"] == "valid"
    assert _run(monkeypatch, _ev(prev_id=None), {"E~q~r~r": MIG})["status"] == "valid"


def test_other_backfill_sources_not_gated(monkeypatch):
    other = dict(MIG, source="backfill:s266_remap")
    prev = {"bbox": [84.36, 979.16, 242.67, 1080.98], "source": "migrate:qiefen-v2+rebase-r4"}
    assert _run(monkeypatch, _ev(), {"E~q~r~r": other, "E~q~r": prev})["status"] == "valid"


def test_sig_unchanged_without_migrated_rows_and_tracks_prev():
    ev = _ev()
    plain = {"E~q~r~r": dict(MIG, source="backfill:ink")}
    base = B._sig([ev], None, plain)
    assert "mig1" not in base
    s1 = B._sig([ev], None, {"E~q~r~r": MIG, "E~q~r": {"bbox": [1, 2, 3, 4]}})
    s2 = B._sig([ev], None, {"E~q~r~r": MIG, "E~q~r": {"bbox": [1, 2, 3, 5]}})
    assert "mig1" in s1 and s1 != s2
