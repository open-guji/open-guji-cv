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
    assert human_chars("vol01", log) == {"vol01:4:1:3": ("太", "太")}


def test_last_verdict_wins_and_other_kinds_ignored(tmp_path):
    log = EventLog(tmp_path)
    log.append([_ev("vol01:4:1:3", {"v": "confirm", "shape": "大"}, 1),
                _ev("vol01:4:1:3", {"v": "confirm", "shape": "太"}, 2),
                _ev("vol01:4:1:4", {"v": "seg_defect", "quality": "truncated"}, 3),
                _ev("vol01:4:1:5", {"v": "not_a_char"}, 4),
                _ev("vol02:1:1:1", {"v": "confirm", "shape": "他"}, 5)])
    got = human_chars("vol01", log)
    assert got == {"vol01:4:1:3": ("太", None)}, "后到覆盖；seg_defect / not_a_char / 别的书不算"


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
