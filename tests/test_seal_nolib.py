# -*- coding: utf-8 -*-
"""H-seal（2026-09-30）：印章遮挡格一律不入字形库。

三件事：入库闸不信事件的 `no_glyph_lib`（`glyphdb_admit`）；判据与 seed_admit 同源
（`steps.occlusion.page_occluded`）；已入库的遮挡格能找出来、撤库走审计
（`research/seal_nolib/find_and_evict.py`）。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, write_product
from open_guji_cv.feedback.consumers import _occluded_lookup, glyphdb_admit
from open_guji_cv.feedback.events import EventTarget, make_event
from open_guji_cv.steps.occlusion import cell_densities, occluded_cells, page_occluded
from open_guji_cv.steps.seed_admit import SeedAdmitParams

# 复用 lib 夹具（空库 + 冻结真页字块）与事件构造
from test_glyphdb_admit import BOOK, PAGE, _confirm, lib  # noqa: F401
from test_seed_admit_occluded import BOOK as SBOOK, PAGE as SPAGE, _page_and_cells

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research" / "seal_nolib"))
import find_and_evict as fe  # noqa: E402


# ── 1. 判据同源 ─────────────────────────────────────────────────────────
def test_page_occluded_is_what_seed_admit_uses(tmp_path, monkeypatch):
    img, cells = _page_and_cells()
    ctx = make_ctx(tmp_path, make_book(SBOOK), raw={SPAGE: img}, monkeypatch=monkeypatch)
    write_product(ctx, "row_segment", SPAGE, cells=cells)
    p = SeedAdmitParams()
    hit = page_occluded(ctx, SPAGE, p)
    assert hit and hit == occluded_cells(cell_densities(img, cells))
    # 读不到 cells 产物 → 空表，不炸
    ctx2 = make_ctx(tmp_path / "x", make_book(SBOOK), raw={SPAGE: img})
    assert page_occluded(ctx2, SPAGE, p) == {}


def test_lookup_fails_open_when_no_products(ws):
    assert _occluded_lookup(BOOK, PAGE) == set()
    assert _occluded_lookup("no-such-book", 1) == set()


# ── 2. glyphdb_admit 入库闸 ─────────────────────────────────────────────
def _count(db):
    return sqlite3.connect(db).execute("SELECT count(*) FROM instances").fetchone()[0]


def test_occluded_cell_is_never_admitted_even_if_event_says_lib_ok(lib):
    db, cells = lib
    pg, col, slot = cells[0]
    r = _confirm(db, cells[0], {"v": "confirm", "shape": "巳", "no_glyph_lib": False},
                 occluded_of=lambda b, p: {(col, slot, "")} if (b, p) == (BOOK, pg) else set())
    assert (r.added, r.no_lib, r.occluded, r.errors) == (0, 1, 1, [])
    assert _count(db) == 0
    assert r.to_dict()["occluded"] == 1


def test_non_occluded_cell_still_admitted(lib):
    db, cells = lib
    pg, col, slot = cells[0]
    other = cells[1]
    r = _confirm(db, cells[0], {"v": "confirm", "shape": "巳", "no_glyph_lib": False},
                 occluded_of=lambda b, p: {(other[1], other[2], "")})
    assert r.added == 1 and r.occluded == 0, r.errors
    assert _count(db) == 1


def test_occluded_gate_covers_v2_prefixed_key_and_memoizes(lib):
    db, cells = lib
    pg, col, slot = cells[0]
    calls = []

    def occ(b, p):
        calls.append((b, p))
        return {(col, slot, "")}
    from test_glyphdb_admit import _ev
    evs = [_ev(f"v2:{BOOK}:{pg}:{col}:{slot}", {"v": "confirm", "shape": "巳"}, pg, col, slot)]
    r = glyphdb_admit(evs, db_path=str(db), occluded_of=occ)
    assert r.occluded == 1 and _count(db) == 0
    assert calls == [(BOOK, pg)]


# ── 3. 找出并撤库 ───────────────────────────────────────────────────────
def _tiny():
    import cv2
    img = np.full((64, 64), 255, np.uint8)
    cv2.rectangle(img, (16, 16), (48, 48), 0, -1)
    return cv2.imencode(".png", img)[1].tobytes()


def _lib_with_seal(tmp_path):
    from open_guji_cv.clustering.glyph_db import GlyphDB
    path = tmp_path / "seal.db"
    db = GlyphDB(str(path))
    db.admit_instance("v2:vol03:3:2:5", "衡", _tiny(), provenance="human")
    db.admit_instance("vol03:3:2:5", "衡", _tiny(), provenance="align")      # 同格机器副本
    db.admit_instance("v2:vol03:3:4:7", "平", _tiny(), provenance="human")
    db.admit_instance("v2:vol03:3:9:1", "正", _tiny(), provenance="human")   # 遮挡外
    db.admit_instance("v2:vol03:4:2:5", "他", _tiny(), provenance="human")   # 别的页
    db.close()
    return path


def _ev(key, shape, seq, lib_ok=False):
    return make_event("vol03-p3", seq, "confirm",
                      EventTarget(step="seed_admit", unit="cell", key=key, book="vol03"),
                      {"v": "confirm", "shape": shape, "no_glyph_lib": lib_ok})


def test_find_lists_only_occluded_cells_in_lib(tmp_path):
    path = _lib_with_seal(tmp_path)
    events = [_ev("vol03:3:2:5", "衡", 1), _ev("vol03:3:4:7", "平", 2),
              _ev("vol03:3:9:1", "正", 3), _ev("vol03:3:6:6", "无", 4)]
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    rows = fe.find("vol03", 3, {(2, 5, ""), (4, 7, ""), (6, 6, "")}, events, conn)
    by = {r["cell"]: r for r in rows}
    assert set(by) == {"3:2:5", "3:4:7", "3:6:6"}
    assert [i["instance_id"] for i in by["3:2:5"]["instances"]] == ["v2:vol03:3:2:5", "vol03:3:2:5"]
    assert by["3:2:5"]["events"][0]["id"] == events[0].id
    assert by["3:6:6"]["in_lib"] is False           # 只有事件、没进库：列出但不撤
    assert sum(len(r["instances"]) for r in rows) == 3


def _run(tmp_path, monkeypatch, path, events, *argv):
    from open_guji_cv.feedback.events import EventLog
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path / "fb"))
    EventLog().append(events)
    out = tmp_path / "rep.json"
    rc = fe.main(["--book", "vol03", "--page", "3", "--db", str(path), "--out", str(out), *argv],
                 occluded_of=lambda b, p: {(2, 5, ""), (4, 7, "")})
    return rc, json.loads(out.read_text(encoding="utf-8"))


def test_dry_run_writes_nothing_and_apply_evicts_with_audit(tmp_path, monkeypatch):
    path = _lib_with_seal(tmp_path)
    events = [_ev("vol03:3:2:5", "衡", 1), _ev("vol03:3:4:7", "平", 2)]
    rc, rep = _run(tmp_path, monkeypatch, path, events)
    assert rc == 0 and not rep["applied"] and rep["instances_to_evict"] == 3
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT count(*) FROM instances").fetchone()[0] == 5
    assert conn.execute("SELECT count(*) FROM evictions").fetchone()[0] == 0
    conn.close()

    # --expect 对不上：整批不动
    rc, rep = _run(tmp_path, monkeypatch, path, [], "--apply", "--expect", "8")
    assert rc == 2 and not rep["applied"]
    assert sqlite3.connect(path).execute("SELECT count(*) FROM instances").fetchone()[0] == 5

    rc, rep = _run(tmp_path, monkeypatch, path, [], "--apply", "--expect", "3")
    assert rc == 0 and rep["applied"] and rep["evicted"] == 3
    conn = sqlite3.connect(path)
    left = {r[0] for r in conn.execute("SELECT instance_id FROM instances")}
    assert left == {"v2:vol03:3:9:1", "v2:vol03:4:2:5"}
    ev = conn.execute("SELECT instance_id, reason FROM evictions ORDER BY instance_id").fetchall()
    assert len(ev) == 3 and all("H-seal" in r for _i, r in ev)
    conn.close()

    # 幂等：再跑找到 0 例，不再写审计
    rc, rep = _run(tmp_path, monkeypatch, path, [], "--apply")
    assert rep["instances_to_evict"] == 0
