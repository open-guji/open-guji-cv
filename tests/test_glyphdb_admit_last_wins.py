"""字形库人裁以最后一票为准（`glyphdb_admit`，sheldon 2026-10-26）。

此前库按消费顺序覆盖：补消费积压时更早的票后消费，把新票压掉（vol04:143:9:16 改判 由 后又被 10-22 的 山 盖回）；
后来判切坏／非字的格，库里更早的人裁刻例也一直留着。"""
from __future__ import annotations

import sqlite3

import cv2
import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.clustering.glyph_db import GlyphDB
from open_guji_cv.feedback.consumers import glyphdb_admit
from open_guji_cv.feedback.events import EventTarget, make_event

BOOK = "abook"
KEY = f"{BOOK}:1:1:1"


def _png() -> bytes:
    img = np.full((80, 80), 255, np.uint8)
    cv2.rectangle(img, (6, 10), (70, 70), 0, 4)
    return cv2.imencode(".png", img)[1].tobytes()


def _ev(payload: dict, ts: str, batch: str, kind: str = "confirm"):
    return make_event(batch, 1, kind, EventTarget(step="seed_admit", unit="cell", key=KEY, book=BOOK,
                                                  page=1, col=1, slot=1), payload, ts=ts)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path / "feedback"))
    p = tmp_path / "g.db"
    g = GlyphDB(p)
    assert g.admit_instance(f"v2:{KEY}", "之", _png(), provenance="human", page="1", col=1, idx=1)
    g.conn.commit()
    g.close()
    return p


def _lib(p) -> str | None:
    c = sqlite3.connect(p)
    try:
        r = c.execute("SELECT char FROM admissions WHERE instance_id=?", (f"v2:{KEY}",)).fetchone()
        return r[0] if r else None
    finally:
        c.close()


def test_older_vote_consumed_later_does_not_override(db):
    new = _ev({"v": "confirm", "shape": "由"}, "2026-10-24T18:15:12Z", "new")
    old = _ev({"v": "confirm", "shape": "山"}, "2026-10-22T19:04:54Z", "old")
    glyphdb_admit([(new, None)], db_path=str(db))
    assert _lib(db) == "由"
    r = glyphdb_admit([(old, None)], db_path=str(db))
    assert _lib(db) == "由" and r.superseded == 1


def test_same_batch_out_of_order_takes_latest(db):
    new = _ev({"v": "confirm", "shape": "由"}, "2026-10-24T18:15:12Z", "new")
    old = _ev({"v": "confirm", "shape": "山"}, "2026-10-22T19:04:54Z", "old")
    glyphdb_admit([(new, None), (old, None)], db_path=str(db))
    assert _lib(db) == "由"


def test_later_seg_defect_or_not_a_char_withdraws(db):
    glyphdb_admit([(_ev({"v": "confirm", "shape": "由"}, "2026-10-24T00:00:00Z", "a"), None)], db_path=str(db))
    r = glyphdb_admit([(_ev({"v": "seg_defect"}, "2026-10-25T00:00:00Z", "b"), None)], db_path=str(db))
    assert _lib(db) is None and r.withdrawn == 1


def test_not_a_char_withdraws_and_older_one_does_not(db):
    glyphdb_admit([(_ev({"v": "confirm", "shape": "由"}, "2026-10-24T00:00:00Z", "a"), None)], db_path=str(db))
    r = glyphdb_admit([(_ev({}, "2026-10-01T00:00:00Z", "old", kind="not_a_char"), None)], db_path=str(db))
    assert _lib(db) == "由" and r.superseded == 1
    glyphdb_admit([(_ev({}, "2026-10-25T00:00:00Z", "new", kind="not_a_char"), None)], db_path=str(db))
    assert _lib(db) is None


def test_legacy_admission_without_event_time_still_overridden(db):
    # 库里刻例证据没有事件（老数据）：照老规矩，后消费的覆盖
    glyphdb_admit([(_ev({"v": "confirm", "shape": "山"}, "2026-09-01T00:00:00Z", "x"), None)], db_path=str(db))
    assert _lib(db) == "山"


def test_confirm_event_with_v_not_a_char_withdraws(db):
    glyphdb_admit([(_ev({"v": "confirm", "shape": "奉"}, "2026-10-01T00:00:00Z", "a"), None)], db_path=str(db))
    glyphdb_admit([(_ev({"v": "not_a_char"}, "2026-10-02T00:00:00Z", "b"), None)], db_path=str(db))
    assert _lib(db) is None
