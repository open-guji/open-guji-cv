# -*- coding: utf-8 -*-
"""删钉垫片 `pin_removed`（GM4 方案第九节，2026-11-26）：pin_state 最后为 removed 的钉，其答案事件 cv 不再当钉用。自造数据。"""
from __future__ import annotations

import json

import open_guji_cv.feedback.events as events
import open_guji_cv.feedback.lookup as lookup
from open_guji_cv.feedback.bindings import _verdict_events, removed_pin_events
from open_guji_cv.feedback.events import Event, EventLog, EventTarget as Target

BOOK = "tbook"


def _ev(i, slot, ch, ts="2026-10-01T00:00:00Z"):
    return Event(id=f"e{i}", batch="b", seq=i, ts=ts, kind="confirm",
                 target=Target(step="seed_admit", unit="cell", key=f"{BOOK}:1:1:{slot}"),
                 payload={"v": "confirm", "shape": ch})


def _state(root, rows):
    d = root / "pins"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{BOOK}.state.jsonl", "a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _pl(pin, v, evs, at):
    return {"id": f"ps-{pin}-{at}", "batch": "pins", "ts": at,
            "payload": {"v": v, "pin_id": pin, "book": BOOK, "events": evs, "reason": "human_correction",
                        "level": "human", "at": at, "by": "t"}}


def test_no_state_file_is_empty(tmp_path):
    assert removed_pin_events(tmp_path) == frozenset()


def test_last_state_wins(tmp_path):
    _state(tmp_path, [_pl("p1", "removed", ["e1"], "2026-11-26T01:00:00Z"),
                      _pl("p2", "removed", ["e2", "e3"], "2026-11-26T01:00:00Z"),
                      _pl("p2", "reactivated", [], "2026-11-26T02:00:00Z"),
                      _pl("p4", "expired", ["e4"], "2026-11-26T01:00:00Z")])
    assert removed_pin_events(tmp_path) == {"e1"}
    _state(tmp_path, [_pl("p1", "reactivated", [], "2026-11-26T03:00:00Z")])     # 文件变了，缓存跟着变
    assert removed_pin_events(tmp_path) == frozenset()


def test_removed_events_dropped_from_human_chars_and_bindings(tmp_path, monkeypatch):
    log = EventLog(tmp_path)
    evs = [_ev(1, 1, "火"), _ev(2, 2, "土"), _ev(3, 2, "金", ts="2026-10-02T00:00:00Z")]
    monkeypatch.setattr(events, "iter_events_readonly", lambda _log: evs)
    assert lookup.human_chars(BOOK, log=log, stale={}, bind=False) == {f"{BOOK}:1:1:1": "火", f"{BOOK}:1:1:2": "金"}
    # 删掉 e3（同格后到的那条）：e2 重新顶上；删掉 e1：那格不再有人裁
    _state(tmp_path, [_pl("pin-x-char-1", "removed", ["e1"], "2026-11-26T01:00:00Z"),
                      _pl("pin-x-char-2", "removed", ["e3"], "2026-11-26T01:00:00Z")])
    assert lookup.human_chars(BOOK, log=log, stale={}, bind=False) == {f"{BOOK}:1:1:2": "土"}
    assert [e.id for e in _verdict_events(BOOK, log, evs)[1]] == ["e2"]
