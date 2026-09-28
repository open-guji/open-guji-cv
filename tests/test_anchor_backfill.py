# -*- coding: utf-8 -*-
"""老裁决补锚档（`feedback/anchor_backfill.py`）与绑定表里的两处修正（overview#152）：
墨框锚按「落在哪一格」绑；`_prev/` 的起点从 manifest 历史反查、查不到不用。"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import numpy as np

import open_guji_cv.feedback.anchor_backfill as A
import open_guji_cv.feedback.bindings as B
from open_guji_cv.feedback.events import EventTarget, make_event


def _cells(boxes):
    cols = {}
    for (col, slot, sub), (x0, y0, x1, y1) in boxes.items():
        q = [(x1, y0), (x0, y0), (x0, y1), (x1, y1)]
        cols.setdefault(col, []).append(NS(slot=slot, sub=sub or None, kind="char", quad_page=q))
    return NS(columns=[NS(col=c, cells=cs) for c, cs in cols.items()])


def _ev(key, seq, shape="X", ts="2026-09-10T00:00:00Z"):
    _, pg, col, slot = key.split(":")
    e = make_event("b", seq, "confirm", EventTarget(step="seed_admit", unit="cell", key=key, book="v",
                                                     page=int(pg), col=int(col), slot=int(slot)),
                   {"v": "confirm", "shape": shape} if shape else {"v": "seg_defect"})
    e.ts = ts
    return e


def _run(monkeypatch, current, events, backfill):
    vers = [("current", B._ts("2026-09-25T00:00:00Z"), float("inf"), current)]
    monkeypatch.setattr(B, "_cells_versions", lambda *a, **k: vers)
    monkeypatch.setattr(B, "_similar", lambda *a, **k: None)
    return B.compute_page("v", 1, events, store=object(), cache=NS(get=lambda *a, **k: None),
                          glyph_db=None, backfill=backfill)


# ── 墨框锚的绑定 ─────────────────────────────────────────────────────────────

def test_ink_inside_same_cell_is_valid(monkeypatch):
    cur = _cells({(1, 5, ""): (0, 400, 100, 500)})
    e = _ev("v:1:1:5", 1)
    r = _run(monkeypatch, cur, [e], {e.id: {"ink_bbox": [10, 410, 90, 490], "source": "backfill:ink"}})[0]
    assert r["status"] == "valid" and B.usable(r) == "v:1:1:5" and r["anchor"] == "backfill:ink"


def test_ink_in_neighbour_slot_rebinds(monkeypatch):
    """整列顺移：当时第 5 格那块墨，现在落在第 6 格。"""
    cur = _cells({(1, 5, ""): (0, 300, 100, 400), (1, 6, ""): (0, 400, 100, 500)})
    e = _ev("v:1:1:5", 1)
    r = _run(monkeypatch, cur, [e], {e.id: {"ink_bbox": [10, 410, 90, 490]}})[0]
    assert r["status"] == "rebound" and B.usable(r) == "v:1:1:6"


def test_ink_straddling_two_cells_goes_to_review(monkeypatch):
    cur = _cells({(1, 5, ""): (0, 400, 100, 450), (1, 6, ""): (0, 450, 100, 500)})
    e = _ev("v:1:1:5", 1)
    r = _run(monkeypatch, cur, [e], {e.id: {"ink_bbox": [10, 410, 90, 490]}})[0]
    assert r["status"] == "review" and B.usable(r) is None


def test_ink_where_no_cell_is_void(monkeypatch):
    cur = _cells({(1, 5, ""): (0, 800, 100, 900)})
    e = _ev("v:1:1:5", 1)
    r = _run(monkeypatch, cur, [e], {e.id: {"ink_bbox": [10, 410, 90, 490]}})[0]
    assert r["status"] == "void" and B.usable(r) is None


def test_live_anchor_beats_backfill(monkeypatch):
    cur = _cells({(1, 5, ""): (0, 400, 100, 500), (1, 6, ""): (0, 500, 100, 600)})
    e = _ev("v:1:1:5", 1)
    e.target.anchor = {"bbox": [0, 400, 100, 500], "source": "live"}
    r = _run(monkeypatch, cur, [e], {e.id: {"ink_bbox": [10, 510, 90, 590]}})[0]
    assert r["status"] == "valid" and r["anchor"] == "live"


def test_backfill_change_invalidates_page_cache():
    e = _ev("v:1:1:5", 1)
    assert B._sig([e], None, {}) != B._sig([e], None, {e.id: {"ink_bbox": [0, 0, 1, 1]}})
    assert B._sig([e], None, {e.id: {"ink_bbox": [0, 0, 1, 1]}}) != B._sig([e], None, {e.id: {"ink_bbox": [0, 0, 2, 2]}})


# ── `_prev/` 起点 ────────────────────────────────────────────────────────────

class _Store:
    def __init__(self, tmp, cur, prev, lines):
        self.tmp, self.cur, self.prev = tmp, cur, prev
        (tmp / "row_segment").mkdir(parents=True, exist_ok=True)
        self.mpath = tmp / "row_segment" / "_manifest.jsonl"
        self.mpath.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")

    def read(self, *a):
        return self.cur

    def manifest(self, *a):
        m = NS(path=self.mpath)
        m.get = lambda k: NS(ts=2000.0)
        return m

    def read_prev(self, *a):
        return self.prev

    def prev_sha(self, *a):
        return "PREV"

    def step_dir(self, *a):
        return self.tmp / "row_segment"


def test_prev_starts_when_manifest_first_wrote_it(tmp_path, monkeypatch):
    import open_guji_cv.report.slots as slots
    monkeypatch.setattr(slots, "cells_step", lambda book: "row_segment")
    st = _Store(tmp_path, "CUR", "OLD", [{"key": "p0001", "sha256": "PREV", "ts": 1500.0},
                                        {"key": "p0001", "sha256": "PREV", "ts": 1700.0},
                                        {"key": "p0001", "sha256": "CURSHA", "ts": 2000.0}])
    v = B._cells_versions("v", 1, st)
    assert [(lab, s, e) for lab, s, e, _ in v] == [("prev", 1500.0, 2000.0), ("current", 2000.0, float("inf"))]


def test_prev_of_unknown_age_is_not_used(tmp_path, monkeypatch):
    """vol02 09-27：快照导入后 `_prev` 是 09-27 的上一版，manifest 里查不到它何时写出——不能把
    09-06 的老裁决当成「按它裁的」（原来起点写死 −∞，4441 条全被判 valid）。"""
    import open_guji_cv.report.slots as slots
    monkeypatch.setattr(slots, "cells_step", lambda book: "row_segment")
    st = _Store(tmp_path, "CUR", "OLD", [{"key": "p0001", "sha256": "CURSHA", "ts": 2000.0}])
    assert [lab for lab, *_ in B._cells_versions("v", 1, st)] == ["current"]


# ── 原图定位与补锚构建 ───────────────────────────────────────────────────────

def _glyph(rng, h=40, w=36):
    g = np.full((h, w), 255, np.uint8)
    g[rng.random((h, w)) < 0.35] = 0
    return g


def test_locate_finds_patch_in_raw_page_top_right_coords():
    rng = np.random.default_rng(0)
    raw = np.full((400, 300), 255, np.uint8)
    g = _glyph(rng)
    raw[100:140, 50:86] = g
    patch = np.full((256, 256), 255, np.uint8)
    patch[108:148, 110:146] = g                    # 字形库格式：白底、墨居中
    r = A.locate(raw, patch)
    assert r["ncc"] > 0.99 and r["ncc"] - r["ncc2"] > A.NCC_MARGIN
    assert r["ink_bbox"] == [300 - 86, 100, 300 - 50, 140]


def test_build_page_ink_and_column_shift():
    """有图块的走墨框；没图块的看整理本：同列 3 个字位一致顺移 −1 才认，单条顺移不认。"""
    rng = np.random.default_rng(1)
    raw = np.full((800, 300), 255, np.uint8)
    g = _glyph(rng)
    raw[110:150, 132:168] = g                      # 第 1 列第 2 格（右上坐标 x 132..168）
    patch = np.full((256, 256), 255, np.uint8)
    patch[100:140, 100:136] = g
    boxes = {(1, s, ""): (100, 100 * (s - 1), 200, 100 * s) for s in range(1, 8)}
    boxes.update({(2, s, ""): (0, 100 * (s - 1), 99, 100 * s) for s in range(1, 8)})
    cells = _cells(boxes)
    align = {(1, s, ""): ch for s, ch in enumerate("甲乙丙丁戊己庚", 1)}
    align.update({(2, s, ""): ch for s, ch in enumerate("子丑寅卯辰巳午", 1)})
    evs = [_ev("v:1:1:2", 1, "乙"),                                       # 墨框：同编号
           _ev("v:1:2:3", 2, "丑"), _ev("v:1:2:4", 3, "寅"), _ev("v:1:2:5", 4, "卯"),   # 整列 −1
           _ev("v:1:1:6", 5, "戊"),                                       # 第 1 列单条 −1：无旁证
           _ev("v:1:1:7", 6, "庚"),                                       # 上下文同编号
           _ev("v:1:1:3", 7, None)]                                       # 无字、无图块
    rows = A.build_page("v", 1, evs, cells, "sha", lambda: raw,
                        lambda k: (None, patch, "乙") if k == "v:1:1:2" else None, align)
    by = {r["key"]: r for r in rows}
    assert by["v:1:1:2"]["evidence"]["method"] == "ink" and by["v:1:1:2"]["evidence"]["at"] == "1:2"
    for k, at in (("v:1:2:3", "2:2"), ("v:1:2:4", "2:3"), ("v:1:2:5", "2:4")):
        assert by[k]["anchor"]["source"] == "backfill:ctx" and by[k]["evidence"]["at"] == at
        assert by[k]["evidence"]["by"] == "column_consensus"
    assert by["v:1:1:6"]["anchor"] is None and "不足以认定" in by["v:1:1:6"]["evidence"]["reason"]
    assert by["v:1:1:7"]["evidence"]["by"] == "same"
    assert by["v:1:1:3"]["anchor"] is None


def test_same_char_accepts_variants_and_ji_family():
    assert A.same_char("已", "巳") and A.same_char("注", "注") and not A.same_char("甲", "乙")
    assert not A.same_char(None, "甲")
