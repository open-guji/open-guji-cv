# -*- coding: utf-8 -*-
"""`EventLog.read_cached`／`iter_all_cached`（2026-10-20，Step7 每页重读事件的提速）。"""
from __future__ import annotations

from open_guji_cv.feedback.events import EventLog, EventTarget, iter_events_readonly, make_event


def _ev(seq, shape, page=1):
    return make_event("b", seq, "confirm",
                      EventTarget(step="seed_admit", unit="cell", key=f"vol02:{page}:1:{seq}",
                                  book="vol02", page=page, col=1, slot=seq),
                      {"v": "confirm", "shape": shape}, source_format="server")


def test_cached_equals_uncached_and_sees_appends(tmp_path):
    log = EventLog(tmp_path)
    log.append([_ev(1, "之"), _ev(2, "也")])
    first = list(log.iter_all_cached())
    assert [e.model_dump() for e in first] == [e.model_dump() for e in log.iter_all()]
    assert list(log.iter_all_cached())[0] is first[0]          # 文件没动：命中缓存，同一批对象
    log.append([_ev(3, "乎")])                                  # 追加 → 文件大小变 → 重读
    again = list(log.iter_all_cached())
    assert [e.payload["shape"] for e in again] == ["之", "也", "乎"]
    assert [e.model_dump() for e in again] == [e.model_dump() for e in log.iter_all()]


def test_readonly_helper_falls_back_for_test_doubles():
    class Fake:
        def iter_all(self):
            yield "x"
    assert list(iter_events_readonly(Fake())) == ["x"]
