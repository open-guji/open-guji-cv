# -*- coding: utf-8 -*-
"""「有噪声 / 字形不完整」同时可以指出是哪个字（2026-09-20 用户定）。

用户原话：「step7 定字裁决，对于有噪声和字形不完整的，应该同时允许我选到底是哪个字。
这样既不影响下一步整理，也反馈给了上游。」

即：`seg_defect` 带 `shape` 时是**两件事同时成立**——
- 定字这件事做完了：文本层出字（`human_chars`）、不再出卡（`decided_cells`）；
- 缺陷照样反馈上游：`gold_add` 留着 quality + shape（consumers.py 本来就留）。
不带 `shape` 的 seg_defect 仍然只是缺陷，两边都不算定字。
"""
from __future__ import annotations

from open_guji_cv.feedback.consumers import _expected_of
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
from open_guji_cv.feedback.lookup import human_chars
from open_guji_cv.review.verdict_view import decided_cells, review_verdicts


def _ev(key: str, payload: dict, seq: int, batch: str = "b"):
    _, pg, col, slot = key.split(":")
    return make_event(batch, seq, "confirm",
                      EventTarget(step="seed_admit", unit="cell", key=key, book="vol01",
                                  page=int(pg), col=int(col), slot=int(slot)),
                      payload, source_format="server")


def test_seg_defect_with_shape_counts_as_decided_and_gives_text(tmp_path):
    log = EventLog(tmp_path)
    log.append([_ev("vol01:5:2:9", {"v": "seg_defect", "quality": "contaminated",
                                    "shape": "手", "reading": "手"}, 1),
                _ev("vol01:5:2:10", {"v": "seg_defect", "quality": "truncated"}, 2)])
    assert human_chars("vol01", log) == {"vol01:5:2:9": "手"}, "带字的要出字"
    assert decided_cells("vol01", log) == {"vol01:5:2:9"}, "带字的算裁过、不再出卡；不带字的照旧待办"


def test_readback_restores_both_shape_and_defect_mark(tmp_path):
    """刷新页面后，字与「有噪声」这个标记都要回来——否则人以为自己没填过。"""
    log = EventLog(tmp_path)
    log.append([_ev("vol01:5:2:9", {"v": "seg_defect", "quality": "contaminated", "shape": "手"}, 1)])
    v = review_verdicts("b", log)["verdicts"]["vol01:5:2:9"]
    assert v["shape"] == "手" and v["done"] == "contaminated"


def test_gold_add_keeps_quality_and_shape(tmp_path):
    """反馈给上游的那一路不受影响：quality 与 shape 都在。"""

    exp = _expected_of(_ev("vol01:5:2:9", {"v": "seg_defect", "quality": "truncated", "shape": "手"}, 1))
    assert exp["quality"] == "truncated" and exp["shape"] == "手"
