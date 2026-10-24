# -*- coding: utf-8 -*-
"""体检撤库（evict／relabel）一个人裁刻例时，同格此前的人裁事件一并作废（GUJI-719 第 4 项）。"""

from __future__ import annotations

import cv2
import numpy as np

from open_guji_cv.clustering.glyph_db import GlyphDB
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
from open_guji_cv.feedback.glyph_audit import glyph_audit
from open_guji_cv.feedback.lookup import human_chars


def _png(k=0):
    img = np.full((64, 64), 255, np.uint8)
    cv2.rectangle(img, (10 + k, 10), (50, 50 - k), 0, 3)
    return cv2.imencode(".png", img)[1].tobytes()


def _confirm(seq, key, shape, ts):
    _, pg, col, slot = key.split(":")
    return make_event("b", seq, "confirm",
                      EventTarget(step="seed_admit", unit="cell", key=key, book="bk",
                                  page=int(pg), col=int(col), slot=int(slot)),
                      {"v": "confirm", "shape": shape}, source_format="server", ts=ts)


def _audit(seq, payload):
    return (make_event("glyphlib-audit", seq, "glyph_audit",
                       EventTarget(step="glyph_audit", unit="cell", key=payload["instance_id"]),
                       payload), None)


def _setup(tmp_path, monkeypatch, provenance):
    db_path = tmp_path / "output" / "glyph.db"
    db_path.parent.mkdir()
    monkeypatch.setenv("GUJI_GLYPH_DB", str(db_path))
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path / "feedback"))
    g = GlyphDB(db_path)
    g.admit_instance("bk:1:1:1", "王", _png(0), provenance=provenance, page="1", col=1, idx=1)
    g.close()
    log = EventLog(tmp_path / "feedback" / "events")
    log.append([_confirm(1, "bk:1:1:1", "王", "2026-10-01T00:00:00Z")])
    return db_path, log


def test_evict_human_voids_old_event_but_not_later_one(tmp_path, monkeypatch):
    db_path, log = _setup(tmp_path, monkeypatch, "human")
    assert human_chars("bk", log, bind=False) == {"bk:1:1:1": "王"}
    r = glyph_audit([_audit(1, {"v": "evict", "key": "k", "instance_id": "bk:1:1:1"})], db_path=str(db_path))
    assert not r.errors, r.errors
    assert human_chars("bk", log, bind=False) == {}          # 撤库后旧人裁不再放行
    log.append([_confirm(2, "bk:1:1:1", "玉", "2099-01-01T00:00:00Z")])
    assert human_chars("bk", log, bind=False) == {"bk:1:1:1": "玉"}   # 撤下之后再裁的照常生效


def test_evict_machine_instance_leaves_events_alone(tmp_path, monkeypatch):
    db_path, log = _setup(tmp_path, monkeypatch, "align")
    r = glyph_audit([_audit(1, {"v": "evict", "key": "k", "instance_id": "bk:1:1:1"})], db_path=str(db_path))
    assert not r.errors, r.errors
    assert human_chars("bk", log, bind=False) == {"bk:1:1:1": "王"}   # 机器进库的撤了，不碰人裁事件
    assert not (tmp_path / "feedback" / "lists" / "stale_verdicts.tsv").exists()
