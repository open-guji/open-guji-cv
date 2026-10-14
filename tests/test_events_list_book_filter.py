"""`events list` 通配批次 + 按册过滤（GUJI-77：vol03-* 汇总不串 vol02 的 key）。"""
from open_guji_cv.cli_v2 import _select_events
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event


def _ev(batch, seq, key):
    return make_event(batch, seq, "verdict", EventTarget(step="seed_admit", unit="cell", key=key))


def test_glob_and_book_filter(tmp_path):
    log = EventLog(tmp_path)
    log.append([_ev("vol03-a", 1, "vol03:1:1:1"), _ev("vol03-a", 2, "vol02:9:9:9")])
    log.append([_ev("vol03-b", 1, "vol03:2:2:2"), _ev("vol02-x", 1, "vol02:1:1:1")])
    allv3 = _select_events(log, "vol03-*")
    assert {e.target.key for e in allv3} == {"vol03:1:1:1", "vol02:9:9:9", "vol03:2:2:2"}
    only = _select_events(log, "vol03-*", "vol03")
    assert {e.target.key for e in only} == {"vol03:1:1:1", "vol03:2:2:2"}
    assert [e.target.key for e in _select_events(log, "vol03-a")] == ["vol03:1:1:1", "vol02:9:9:9"]
    assert len(_select_events(log, None, "vol02")) == 2
