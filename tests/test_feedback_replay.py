# -*- coding: utf-8 -*-
"""rebuild 后补放人裁（`feedback/replay.py`，值守 #115）：两次导出之间审进库的格，rebuild 不丢；
水位线之前的历史事件不重放（体检撤掉的刻例不复活）；机器刻例、进库闸拦下的不重放；--no-replay 跳过。"""

from __future__ import annotations

import json
from argparse import Namespace

import cv2
import numpy as np
import pytest

import open_guji_cv.cli_glyph_db as main_mod
from open_guji_cv.clustering.glyph_db import GlyphDB, export_store
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event


def _img(k: int) -> np.ndarray:
    img = np.full((80, 80), 255, np.uint8)
    cv2.rectangle(img, (10 + k, 12), (68, 66 - k), 0, 5)
    return img


@pytest.fixture
def ws(tmp_path, monkeypatch):
    for k in ("GUJI_GLYPH_DB", "GUJI_GLYPH_STORE", "GUJI_FEEDBACK_DIR", "GUJI_PRODUCTS_DIR"):
        monkeypatch.delenv(k, raising=False)
    w = tmp_path / "qtw"
    (w / "output").mkdir(parents=True)
    monkeypatch.setenv("GUJI_WORKSPACE", str(w))
    from open_guji_cv.products.cache import ImageCache
    cache = ImageCache()
    for i in range(1, 6):
        cache.put("v006", "char_patch", f"p0001c01s{i}", _img(i))
    # 真源：一条旧人裁（水位线 = 它的准入时间）
    db = GlyphDB(w / "output" / "glyph.db")
    db.set_book_edition("quantangwen")
    db.admit_instance("v2:v006:1:1:1", "之", cv2.imencode(".png", _img(1))[1].tobytes(),
                      provenance="human")
    db.conn.execute("UPDATE admissions SET admitted_at='2026-09-27T22:00:00+00:00'")
    db.conn.commit()
    export_store(db, w / "output" / "glyph_store")
    db.close()
    return w


def _ev(batch, seq, slot, ch, ts, **extra):
    return make_event(batch, seq, "confirm",
                      EventTarget(step="seed_admit", unit="cell", key=f"v006:1:1:{slot}",
                                  book="v006", page=1, col=1, slot=slot),
                      {"v": "confirm", "shape": ch, **extra.pop("payload", {})}, ts=ts, **extra)


def _rebuild(**kw):
    main_mod.cmd_glyph_db(Namespace(action="rebuild", path=None, store=None, **kw))


def _ids(w):
    db = GlyphDB(w / "output" / "glyph.db")
    ids = {r[0] for r in db.conn.execute("SELECT instance_id FROM admissions")}
    db.close()
    return ids


def test_rebuild_replays_events_after_watermark(ws):
    log = EventLog(ws / "feedback")
    log.append([_ev("srv", 1, 2, "以", "2026-09-27T23:30:00Z"),            # 审进库、还没导出
                _ev("srv", 2, 3, "令", "2026-09-27T20:00:00Z"),            # 水位线前的历史：不重放
                _ev("auto", 1, 4, "天", "2026-09-27T23:31:00Z", actor="model",
                    payload={"source": "auto"}),                            # 机器刻例：不重放
                _ev("srv", 3, 5, "大", "2026-09-27T23:32:00Z")])            # 进库闸拦下：不重放
    gated = [e for e in log.read("srv") if e.seq == 3]
    log.mark_consumed("glyphdb_admit", gated, note="book_lib_sync gated: 本书库「大」已满")
    _rebuild()
    assert _ids(ws) == {"v2:v006:1:1:1", "v2:v006:1:1:2"}


def test_no_replay_flag(ws):
    EventLog(ws / "feedback").append([_ev("srv", 1, 2, "以", "2026-09-27T23:30:00Z")])
    _rebuild(no_replay=True)
    assert _ids(ws) == {"v2:v006:1:1:1"}


def test_replay_is_idempotent_and_evicted_history_stays_out(ws):
    from open_guji_cv.clustering.audit import evict_instance
    EventLog(ws / "feedback").append([_ev("srv", 1, 2, "以", "2026-09-27T23:30:00Z")])
    _rebuild()
    _rebuild()
    assert _ids(ws) == {"v2:v006:1:1:1", "v2:v006:1:1:2"}
    # 旧刻例被体检撤掉后导出：它的旧事件（若有）在水位线前，不会被复活
    db = GlyphDB(ws / "output" / "glyph.db")
    evict_instance(db, "v2:v006:1:1:1")
    db.conn.commit()
    export_store(db, ws / "output" / "glyph_store")
    db.close()
    EventLog(ws / "feedback").append([_ev("old", 1, 1, "之", "2026-09-27T21:00:00Z")])
    _rebuild()
    assert "v2:v006:1:1:1" not in _ids(ws)


def test_empty_store_does_not_replay_history(tmp_path, monkeypatch):
    from open_guji_cv.feedback.replay import replay_after_rebuild
    (tmp_path / "store").mkdir()
    r = replay_after_rebuild(tmp_path / "g.db", tmp_path / "store", tmp_path / "feedback")
    assert r["watermark"] is None and "skipped" in r


# ── admit_candidate（待纳入裁决，overview#201）─────────────────────────────────

def _cand(batch, seq, slot, v, ts, shape="以", **extra):
    payload = {"v": v, "char": shape, "list": "t", "evidence": {}}
    if v == "admit":
        payload["shape"] = shape
    return make_event(batch, seq, "admit_candidate",
                      EventTarget(step="glyph_candidate", unit="cell", key=f"v006:1:1:{slot}",
                                  book="v006", page=1, col=1, slot=slot),
                      payload, ts=ts, **extra)


def _chars(w):
    db = GlyphDB(w / "output" / "glyph.db")
    rows = dict(db.conn.execute("SELECT instance_id, char FROM admissions"))
    prov = dict(db.conn.execute("SELECT instance_id, provenance FROM admissions"))
    db.close()
    return rows, prov


def test_admit_candidate_admit_goes_in_like_confirm(ws):
    # 水位线之前的裁决也要进：线上从来没有消费者吃过它
    EventLog(ws / "feedback").append([
        _cand("candidates-t", 1, 2, "admit", "2026-09-27T20:00:00Z", shape="以"),
        _cand("candidates-t", 2, 3, "reject", "2026-09-27T23:30:00Z", shape="令"),
        _cand("candidates-t", 3, 4, "unclear", "2026-09-27T23:31:00Z", shape="天")])
    _rebuild()
    chars, prov = _chars(ws)
    assert chars == {"v2:v006:1:1:1": "之", "v2:v006:1:1:2": "以"}
    assert prov["v2:v006:1:1:2"] == "human"


def test_admit_candidate_latest_verdict_wins(ws):
    EventLog(ws / "feedback").append([
        _cand("candidates-t", 1, 2, "admit", "2026-09-27T23:00:00Z", shape="以"),
        _cand("candidates-t", 2, 2, "reject", "2026-09-27T23:10:00Z", shape="以"),   # 改判不收
        _cand("candidates-t", 3, 3, "reject", "2026-09-27T23:00:00Z", shape="令"),
        _cand("candidates-t", 4, 3, "admit", "2026-09-27T23:10:00Z", shape="令")])   # 改判收
    _rebuild()
    chars, _ = _chars(ws)
    assert chars == {"v2:v006:1:1:1": "之", "v2:v006:1:1:3": "令"}


def test_admit_candidate_model_actor_skipped(ws):
    # 非单字的字形在 EventLog.append 就被拒写了，到不了这里；机器写的裁决不重放
    EventLog(ws / "feedback").append([
        _cand("candidates-t", 2, 3, "admit", "2026-09-27T23:00:00Z", shape="令", actor="model")])
    _rebuild()
    chars, _ = _chars(ws)
    assert chars == {"v2:v006:1:1:1": "之"}


def test_admit_candidate_consumed_once_and_evicted_stays_out(ws):
    from open_guji_cv.clustering.audit import evict_instance
    from open_guji_cv.feedback.replay import replay_admit_candidates
    log = EventLog(ws / "feedback")
    log.append([_cand("candidates-t", 1, 2, "admit", "2026-09-27T20:00:00Z", shape="以")])
    db_path = ws / "output" / "glyph.db"
    r1 = replay_admit_candidates(db_path, ws / "feedback")
    assert r1["to_admit"] == 1 and r1["result"]["added"] == 1
    assert len(log.consumed_ids("glyphdb_admit")) == 1
    r2 = replay_admit_candidates(db_path, ws / "feedback")        # 记过账：不再送
    assert r2["to_admit"] == 0 and r2["already_consumed"] == 1
    # 导出后被体检撤掉：rebuild 时它在水位线之前、已记账 → 不复活
    db = GlyphDB(db_path)
    db.admit_instance("v2:v006:1:1:5", "大", cv2.imencode(".png", _img(5))[1].tobytes(),
                      provenance="human")
    db.conn.execute("UPDATE admissions SET admitted_at='2026-09-27T22:30:00+00:00'")
    evict_instance(db, "v2:v006:1:1:2")
    db.conn.commit()
    export_store(db, ws / "output" / "glyph_store")
    db.close()
    _rebuild()
    assert "v2:v006:1:1:2" not in _ids(ws)


def test_admit_candidate_after_watermark_replayed_even_if_consumed(ws):
    """收了、记了账，但 rebuild 在导出之前：水位线之后的已记账裁决要补回来。"""
    from open_guji_cv.feedback.replay import replay_admit_candidates
    log = EventLog(ws / "feedback")
    log.append([_cand("candidates-t", 1, 2, "admit", "2026-09-27T23:30:00Z", shape="以")])
    replay_admit_candidates(ws / "output" / "glyph.db", ws / "feedback")
    _rebuild()                                                    # 真源里还没有它
    assert "v2:v006:1:1:2" in _ids(ws)
    assert len(log.consumed_ids("glyphdb_admit")) == 1            # 不重复记账


def test_admit_candidate_flip_after_admit_is_reported_not_evicted(ws):
    from open_guji_cv.feedback.replay import replay_admit_candidates
    log = EventLog(ws / "feedback")
    log.append([_cand("candidates-t", 1, 2, "admit", "2026-09-27T23:00:00Z", shape="以")])
    replay_admit_candidates(ws / "output" / "glyph.db", ws / "feedback")
    log.append([_cand("candidates-t", 2, 2, "reject", "2026-09-27T23:40:00Z", shape="以")])
    r = replay_admit_candidates(ws / "output" / "glyph.db", ws / "feedback")
    assert r["admit_then_reject"] == ["v006:1:1:2"]
    assert "v2:v006:1:1:2" in _ids(ws)
