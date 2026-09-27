# -*- coding: utf-8 -*-
"""打回并入绑定表（总览/13 并入总览/15，2026-09-27）：`feedback/returns.py` 的分类/展开，
以及 `bindings.compute_page` 折进 `return_to`/`return_reason`/`return_status` 三个字段。
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import open_guji_cv.feedback.bindings as B
from open_guji_cv.feedback.events import EventTarget, make_event
from open_guji_cv.feedback.returns import affected_slots, classify_return, resolve_status


def _cells(boxes):
    cols = {}
    for (col, slot, sub), (x0, y0, x1, y1) in boxes.items():
        q = [(x1, y0), (x0, y0), (x0, y1), (x1, y1)]
        cols.setdefault(col, []).append(NS(slot=slot, sub=sub or None, kind="char", quad_page=q))
    return NS(columns=[NS(col=c, cells=cs) for c, cs in cols.items()])


def _confirm(key, seq, payload, ts="2026-09-27T00:00:00Z", anchor=None):
    _, pg, col, slot = key.split(":")
    e = make_event("b", seq, "confirm", EventTarget(step="seed_admit", unit="cell", key=key, book="v",
                                                     page=int(pg), col=int(col), slot=int(slot), anchor=anchor),
                   payload)
    e.ts = ts
    return e


def _cutline(book, page, col, slot_above, slot_below, verdict, seq, ts="2026-09-27T00:00:00Z"):
    key = f"{book}:{page}:{col}:{slot_above}"
    e = make_event("b", seq, "cutline",
                   EventTarget(step="row_segment", unit="column", key=key, book=book, page=page, col=col),
                   {"verdict": verdict, "slot_above": slot_above, "slot_below": slot_below})
    e.ts = ts
    return e


def _resolve(key, resolution, seq, ts):
    _, pg, col, slot = key.split(":")
    e = make_event("b", seq, "return_resolve",
                   EventTarget(step="row_segment", unit="cell", key=key, book="v",
                              page=int(pg), col=int(col), slot=int(slot)),
                   {"resolution": resolution})
    e.ts = ts
    return e


def _run(monkeypatch, current, events, return_events=None, sim=None):
    vers = [("current", B._ts("2026-09-25T00:00:00Z"), float("inf"), current)]
    monkeypatch.setattr(B, "_cells_versions", lambda *a, **k: vers)
    monkeypatch.setattr(B, "_similar", lambda *a, **k: sim)
    cache = NS(get=lambda *a, **k: None)
    return B.compute_page("v", 1, events, store=object(), cache=cache, glyph_db=None,
                          return_events=return_events)


# ── classify_return / affected_slots / resolve_status（纯函数）──────────────

def test_classify_return_seg_defect_and_cutline_and_slots():
    assert classify_return(_confirm("v:1:1:5", 1, {"v": "seg_defect", "quality": "contaminated"})) == \
        ("row_segment", "seg_noise")
    assert classify_return(_confirm("v:1:1:5", 1, {"v": "seg_defect", "quality": "truncated"})) == \
        ("row_segment", "seg_truncated")
    assert classify_return(_confirm("v:1:1:5", 1, {"v": "seg_defect", "quality": "clean"})) is None
    assert classify_return(_confirm("v:1:1:5", 1, {"v": "confirm", "shape": "甲"})) is None
    assert classify_return(_cutline("v", 1, 1, 5, 6, "overlap", 1)) == ("row_segment", "cut_unresolvable")
    assert classify_return(_cutline("v", 1, 1, 5, 6, "ok", 1)) is None
    e = make_event("b", 1, "n_body_slots", EventTarget(step="row_segment", unit="column", key="v:1:1",
                                                       book="v", page=1, col=1), {"n_slots": 7})
    assert classify_return(e) == ("row_segment", "slot_count")


def test_affected_slots_cutline_picks_the_two_adjacent_cells():
    cur_idx = B._cell_index(_cells({(1, 5, ""): (0, 400, 100, 450), (1, 6, ""): (0, 450, 100, 500),
                                    (1, 7, ""): (0, 500, 100, 550)}))
    ev = _cutline("v", 1, 1, 5, 6, "overlap", 1)
    assert set(affected_slots(ev, cur_idx)) == {(1, 5, ""), (1, 6, "")}


def test_affected_slots_n_body_slots_picks_whole_column():
    cur_idx = B._cell_index(_cells({(1, 5, ""): (0, 400, 100, 450), (1, 6, ""): (0, 450, 100, 500),
                                    (2, 1, ""): (0, 0, 100, 50)}))
    e = make_event("b", 1, "n_body_slots", EventTarget(step="row_segment", unit="column", key="v:1:1",
                                                       book="v", page=1, col=1), {"n_slots": 2})
    assert set(affected_slots(e, cur_idx)) == {(1, 5, ""), (1, 6, "")}


def test_resolve_status_open_then_fixed():
    trig = _confirm("v:1:1:5", 1, {"v": "seg_defect", "quality": "truncated"}, ts="2026-09-27T00:00:00Z")
    assert resolve_status([trig]) == "open"
    fix = _resolve("v:1:1:5", "fixed", 2, "2026-09-27T01:00:00Z")
    assert resolve_status([trig, fix]) == "fixed"
    # 结案之后又新来一条触发：重新回到 open（不该被旧的「已修」盖住新问题）
    trig2 = _confirm("v:1:1:5", 3, {"v": "seg_defect", "quality": "contaminated"}, ts="2026-09-27T02:00:00Z")
    assert resolve_status([trig, fix, trig2]) == "open"


# ── compute_page 集成：折进已有行 ─────────────────────────────────────────

def test_seg_defect_confirm_sets_return_fields_on_its_own_row(monkeypatch):
    cur = _cells({(1, 5, ""): (0, 400, 100, 500)})
    ev = _confirm("v:1:1:5", 1, {"v": "seg_defect", "quality": "contaminated"})
    rows = _run(monkeypatch, cur, [ev])
    assert rows[0]["return_to"] == "row_segment"
    assert rows[0]["return_reason"] == "seg_noise"
    assert rows[0]["return_status"] == "open"


def test_clean_confirm_has_no_return_fields(monkeypatch):
    cur = _cells({(1, 5, ""): (0, 400, 100, 500)})
    ev = _confirm("v:1:1:5", 1, {"v": "confirm", "shape": "甲"})
    rows = _run(monkeypatch, cur, [ev])
    assert "return_to" not in rows[0] and "return_reason" not in rows[0] and "return_status" not in rows[0]


def test_cutline_event_folds_return_fields_into_matching_confirm_rows(monkeypatch):
    """列级 cutline 打回，展开到它影响的两格——那两格已经各有一条 confirm 行时，折进去。"""
    cur = _cells({(1, 5, ""): (0, 400, 100, 450), (1, 6, ""): (0, 450, 100, 500)})
    confirms = [_confirm("v:1:1:5", 1, {"v": "confirm", "shape": "甲"}),
               _confirm("v:1:1:6", 2, {"v": "confirm", "shape": "乙"})]
    cutline = _cutline("v", 1, 1, 5, 6, "overlap", 3)
    rows = _run(monkeypatch, cur, confirms, return_events=[cutline])
    by_key = {r["key"]: r for r in rows}
    assert by_key["v:1:1:5"]["return_reason"] == "cut_unresolvable"
    assert by_key["v:1:1:6"]["return_reason"] == "cut_unresolvable"
    assert by_key["v:1:1:5"]["return_status"] == "open"


def test_column_trigger_without_own_confirm_row_is_not_synthesized(monkeypatch):
    """只有列级触发、这一格自己没有 confirm 事件：本轮不新造行（见 compute_page 文档）。"""
    cur = _cells({(1, 5, ""): (0, 400, 100, 450), (1, 6, ""): (0, 450, 100, 500)})
    cutline = _cutline("v", 1, 1, 5, 6, "overlap", 1)
    rows = _run(monkeypatch, cur, [], return_events=[cutline])
    assert rows == []


def test_repeated_consumption_of_same_column_event_does_not_duplicate_rows(monkeypatch):
    """同一条列级事件重复消费（同一批 return_events 再算一次）：行数不翻倍——幂等。"""
    cur = _cells({(1, 5, ""): (0, 400, 100, 450), (1, 6, ""): (0, 450, 100, 500)})
    confirms = [_confirm("v:1:1:5", 1, {"v": "confirm", "shape": "甲"}),
               _confirm("v:1:1:6", 2, {"v": "confirm", "shape": "乙"})]
    cutline = _cutline("v", 1, 1, 5, 6, "overlap", 3)
    rows1 = _run(monkeypatch, cur, confirms, return_events=[cutline])
    rows2 = _run(monkeypatch, cur, confirms, return_events=[cutline])
    assert len(rows1) == len(rows2) == 2
    assert rows1 == rows2


def test_resolve_event_marks_row_fixed(monkeypatch):
    """`return_resolve` 走 `return_events`（`_return_trigger_events` 收的四种之一），
    不进 `events`——那是 confirm+cell 专用（`_verdict_events`），真实调用里 `return_resolve`
    也从不会出现在 `events` 里。"""
    cur = _cells({(1, 5, ""): (0, 400, 100, 500)})
    trig = _confirm("v:1:1:5", 1, {"v": "seg_defect", "quality": "truncated"}, ts="2026-09-27T00:00:00Z")
    fix = _resolve("v:1:1:5", "fixed", 2, "2026-09-27T01:00:00Z")
    rows = _run(monkeypatch, cur, [trig], return_events=[fix])
    assert len(rows) == 1
    assert rows[0]["return_status"] == "fixed"
