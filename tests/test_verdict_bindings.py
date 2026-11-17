# -*- coding: utf-8 -*-
"""人裁重绑定（`feedback/bindings.py`，总览/15）：按锚框在现行切分里找回裁决对应的格。"""
from __future__ import annotations

from types import SimpleNamespace as NS

import open_guji_cv.feedback.bindings as B
from open_guji_cv.feedback.events import EventTarget, make_event


def _cells(boxes):
    """boxes: {(col, slot, sub): (x0, y0, x1, y1)} → 伪 PageCells。"""
    cols = {}
    for (col, slot, sub), (x0, y0, x1, y1) in boxes.items():
        q = [(x1, y0), (x0, y0), (x0, y1), (x1, y1)]
        cols.setdefault(col, []).append(NS(slot=slot, sub=sub or None, kind="char", quad_page=q))
    return NS(columns=[NS(col=c, cells=cs) for c, cs in cols.items()])


def _ev(key, seq, anchor=None, ts="2026-09-10T00:00:00Z"):
    _, pg, col, slot = key.split(":")
    e = make_event("b", seq, "confirm", EventTarget(step="seed_admit", unit="cell", key=key, book="v",
                                                     page=int(pg), col=int(col), slot=int(slot), anchor=anchor),
                   {"v": "confirm", "shape": "X"})
    e.ts = ts
    return e


def _run(monkeypatch, current, events, sim=None, older=None):
    vers = []
    if older is not None:
        vers.append(("bak:20260919", float("-inf"), B._ts("2026-09-20T00:00:00Z"), older))
    vers.append(("current", B._ts("2026-09-25T00:00:00Z"), float("inf"), current))
    monkeypatch.setattr(B, "_cells_versions", lambda *a, **k: vers)
    monkeypatch.setattr(B, "_similar", lambda *a, **k: sim)
    cache = NS(get=lambda *a, **k: None)
    return B.compute_page("v", 1, events, store=object(), cache=cache, glyph_db=None)


def test_same_cell_boundary_nudge_is_valid(monkeypatch):
    cur = _cells({(1, 5, ""): (0, 400, 100, 500)})
    a = {"bbox": [0, 405, 100, 498], "source": "live"}
    r = _run(monkeypatch, cur, [_ev("v:1:1:5", 1, a)], sim=0.99)[0]
    assert r["status"] == "valid" and r["bound"] == "v:1:1:5"


def test_column_shift_rebinds_to_neighbour_slot(monkeypatch):
    """列内上方多切了一格：原来第 5 格那个字现在是第 6 格。"""
    cur = _cells({(1, 5, ""): (0, 300, 100, 400), (1, 6, ""): (0, 400, 100, 500)})
    a = {"bbox": [0, 400, 100, 500], "source": "live"}
    r = _run(monkeypatch, cur, [_ev("v:1:1:5", 1, a)], sim=0.99)[0]
    assert r["status"] == "rebound" and r["bound"] == "v:1:1:6"


def test_split_cell_goes_to_review(monkeypatch):
    cur = _cells({(1, 5, ""): (0, 400, 100, 450), (1, 6, ""): (0, 450, 100, 500)})
    a = {"bbox": [0, 400, 100, 500], "source": "live"}
    r = _run(monkeypatch, cur, [_ev("v:1:1:5", 1, a)], sim=0.99)[0]
    assert r["status"] == "review"


def test_same_box_ignores_patch_difference(monkeypatch):
    """框没动 = 原图同一块像素 = 同一个字；图块因 Step4 改动而变不算（bxgb 6 例 IoU=1.0、相似度 0.61~0.87）。"""
    cur = _cells({(1, 5, ""): (0, 400, 100, 500)})
    a = {"bbox": [0, 400, 100, 500], "source": "live"}
    r = _run(monkeypatch, cur, [_ev("v:1:1:5", 1, a)], sim=0.6)[0]
    assert r["status"] == "valid"


def test_partial_overlap_with_different_shape_goes_to_review(monkeypatch):
    cur = _cells({(1, 5, ""): (0, 430, 100, 530)})
    a = {"bbox": [0, 400, 100, 500], "source": "live"}
    r = _run(monkeypatch, cur, [_ev("v:1:1:5", 1, a)], sim=0.6)[0]
    assert r["status"] == "review"


def test_cell_shrunk_to_half_is_still_same(monkeypatch):
    """夹注判法改了、格只剩右半（bxgb 3:4:5「覿」IoU 0.50）：新格整个在锚框里且只它一格，图块像 → 有效。"""
    cur = _cells({(1, 5, ""): (50, 400, 100, 500)})
    a = {"bbox": [0, 400, 100, 500], "source": "live"}
    r = _run(monkeypatch, cur, [_ev("v:1:1:5", 1, a)], sim=0.95)[0]
    assert r["status"] == "valid"


def test_cell_gone_is_void(monkeypatch):
    cur = _cells({(1, 5, ""): (0, 800, 100, 900)})
    a = {"bbox": [0, 400, 100, 500], "source": "live"}
    r = _run(monkeypatch, cur, [_ev("v:1:1:5", 1, a)], sim=None)[0]
    assert r["status"] == "void" and B.usable(r) is None


def test_legacy_event_backfills_from_older_version(monkeypatch):
    """老裁决没有锚：按裁决时间取当时那一版切分的框（这里是备份版），再在现行版里找回。"""
    older = _cells({(1, 5, ""): (0, 400, 100, 500)})
    cur = _cells({(1, 5, ""): (0, 300, 100, 400), (1, 6, ""): (0, 400, 100, 500)})
    r = _run(monkeypatch, cur, [_ev("v:1:1:5", 1, None, ts="2026-09-10T00:00:00Z")], sim=None, older=older)[0]
    assert r["status"] == "rebound" and r["bound"] == "v:1:1:6" and r["anchor"] == "backfill:bak:20260919"


def test_legacy_without_anchor_before_current_split_is_not_used(monkeypatch):
    cur = _cells({(1, 5, ""): (0, 400, 100, 500)})
    r = _run(monkeypatch, cur, [_ev("v:1:1:9", 1, None, ts="2026-09-10T00:00:00Z")], sim=None)[0]
    assert r["status"] == "unanchored" and B.usable(r) is None


def test_page_cache_follows_patch_step_and_stamps_patches(monkeypatch, tmp_path):
    """缓存键要含字块那一步（cell_shrink）的 sha，字块图要验戳（D 10-19 vol01 云端重跑踩到：
    Step3 没变、字块重算了，旧缓存照样采信，行里的 fp 是对着旧字块算的，人裁 100 多格丢成 □）。"""
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.products.store import ProductStore
    st = ProductStore(tmp_path / "products")

    def put(step, text):
        p = st.path("v", step, page_key(1))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    put("row_segment", "cells-1")
    put("cell_shrink", "shrink-1")
    monkeypatch.setattr(B, "_bindings_dir", lambda book: tmp_path / "bindings" / book)
    seen = []
    monkeypatch.setattr(B, "compute_page", lambda *a, **k: seen.append(k["patch_stamp"]) or [])
    B.page_bindings("v", 1, [], store=st, backfill={})
    B.page_bindings("v", 1, [], store=st, backfill={})
    assert seen == [st.sha("v", "cell_shrink", page_key(1))]          # 第二次命中缓存
    put("cell_shrink", "shrink-2")                                       # Step3 不变、字块重算
    B.page_bindings("v", 1, [], store=st, backfill={})
    assert seen[-1] == st.sha("v", "cell_shrink", page_key(1)) and len(seen) == 2


def test_compute_page_passes_patch_stamp_to_cache(monkeypatch):
    got = []
    monkeypatch.setattr(B, "_cells_versions", lambda *a, **k: [("current", 0.0, float("inf"), _cells({(1, 1, ""): (0, 0, 10, 10)}))])
    cache = NS(get=lambda *a, **k: got.append(k.get("stamp")))
    ev = _ev("v:1:1:1", 1, anchor={"bbox": [0, 0, 10, 10], "evidence": {"fp": "x"}})
    B.compute_page("v", 1, [ev], store=object(), cache=cache, glyph_db=None, patch_stamp="S")
    assert got and set(got) == {"S"}
