# -*- coding: utf-8 -*-
"""`feedback.lookup.human_chars`：事件侧的人裁定字，勾了「字形不入库」也算定了字（2026-09-20）。

bxgb 11 个「已裁未放行」里 5 个是人定了字但勾了不入库——Step7 只从字形库拿人裁，
这 5 个永远未放行、文本层出阙文、定字台又不再出卡，两边都不管。
"""
from __future__ import annotations

from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
from open_guji_cv.feedback.lookup import human_chars


def _ev(key: str, payload: dict, seq: int, batch: str = "b"):
    _, pg, col, slot = key.split(":")
    return make_event(batch, seq, "confirm",
                      EventTarget(step="seed_admit", unit="cell", key=key, book="vol01",
                                  page=int(pg), col=int(col), slot=int(slot)),
                      payload, source_format="server")


def test_no_glyph_lib_confirm_still_counts(tmp_path):
    log = EventLog(tmp_path)
    log.append([_ev("vol01:4:1:3", {"v": "confirm", "shape": "太", "reading": "太", "no_glyph_lib": True}, 1)])
    assert human_chars("vol01", log) == {"vol01:4:1:3": "太"}


def test_last_verdict_wins_and_other_kinds_ignored(tmp_path):
    log = EventLog(tmp_path)
    log.append([_ev("vol01:4:1:3", {"v": "confirm", "shape": "大"}, 1),
                _ev("vol01:4:1:3", {"v": "confirm", "shape": "太"}, 2),
                _ev("vol01:4:1:4", {"v": "seg_defect", "quality": "truncated"}, 3),
                _ev("vol01:4:1:5", {"v": "not_a_char"}, 4),
                _ev("vol02:1:1:1", {"v": "confirm", "shape": "他"}, 5)])
    got = human_chars("vol01", log)
    assert got == {"vol01:4:1:3": "太"}, "后到覆盖；seg_defect / not_a_char / 别的书不算"


def test_later_step8_fix_beats_earlier_step7_by_time(tmp_path):
    """按时间后到覆盖，不按批次名：`bxgb-list-…` 排在 `bxgb-collate` 后面，
    按批次名排会把 Step8 复核改好的字盖回 Step7 的旧字（2026-09-24）。"""
    from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
    log = EventLog(tmp_path)
    t = EventTarget(step="x", unit="cell", key="bxgb:3:1:1", book="bxgb")
    log.append([make_event("bxgb-list-lu-decide", 1, "confirm", t,
                           {"v": "confirm", "shape": "甲"}, ts="2026-09-20T00:00:00Z"),
                make_event("bxgb-collate", 1, "confirm", t,
                           {"v": "confirm", "shape": "乙"}, ts="2026-09-24T00:00:00Z")])
    assert human_chars("bxgb", log)["bxgb:3:1:1"][0] == "乙"


def test_stale_mark_voids_earlier_verdicts_only(tmp_path):
    """库里撤下（human_stale_<日期>）的位：那天及以前的事件作废，之后再裁的照常生效（2026-09-25）。"""
    log = EventLog(tmp_path)
    old = _ev("vol01:4:1:3", {"v": "confirm", "shape": "目"}, 1)
    old.ts = "2026-09-10T05:00:00Z"
    log.append([old])
    assert human_chars("vol01", log, stale={"vol01:4:1:3": "20260925"}) == {}
    new = _ev("vol01:4:1:3", {"v": "confirm", "shape": "文"}, 2)
    new.ts = "2026-09-26T01:00:00Z"
    log.append([new])
    assert human_chars("vol01", log, stale={"vol01:4:1:3": "20260925"}) == {"vol01:4:1:3": "文"}


def test_stale_mark_minute_precision_same_day(tmp_path):
    log = EventLog(tmp_path)
    a = _ev("vol01:4:1:3", {"v": "confirm", "shape": "目"}, 1); a.ts = "2026-09-25T06:00:00Z"
    b = _ev("vol01:4:1:3", {"v": "confirm", "shape": "文"}, 2); b.ts = "2026-09-25T08:00:00Z"
    log.append([a, b])
    assert human_chars("vol01", log, stale={"vol01:4:1:3": "20260925T0700"}) == {"vol01:4:1:3": "文"}


def test_missing_events_dir_raises(tmp_path, monkeypatch):
    """读工作区事件日志、目录却不存在 → 报错，不当「没人裁过」（2026-10-25，殿本 vol06/10 没设 GUJI_WORKSPACE）。"""
    import pytest
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path / "nowhere"))
    monkeypatch.delenv("GUJI_ALLOW_NO_EVENTS", raising=False)
    with pytest.raises(FileNotFoundError, match="GUJI_WORKSPACE"):
        human_chars("vol01", stale={})
    monkeypatch.setenv("GUJI_ALLOW_NO_EVENTS", "1")
    assert human_chars("vol01", stale={}) == {}


def test_unbound_for_missing_patch_raises(tmp_path, monkeypatch):
    """绑定行 `why=no_patch`（有当时的图、现格字块图拿不到）→ 报错，不悄悄当绑丢（2026-10-25，vol10 丢 68/146）。"""
    import pytest

    import open_guji_cv.feedback.bindings as B
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path))
    ev = _ev("vol01:4:1:3", {"v": "confirm", "shape": "太"}, 1)
    EventLog(tmp_path).append([ev])
    row = {"event": ev.id, "key": ev.target.key, "status": "unanchored", "bound": None, "why": "no_patch"}
    monkeypatch.setattr(B, "book_bindings", lambda book, log=None: {ev.id: row})
    monkeypatch.delenv("GUJI_ALLOW_LOST_HUMAN", raising=False)
    with pytest.raises(RuntimeError, match="字块图"):
        human_chars("vol01", stale={})
    monkeypatch.setenv("GUJI_ALLOW_LOST_HUMAN", "1")
    lost = {}
    assert human_chars("vol01", stale={}, lost=lost) == {} and "vol01:4:1:3" in lost
