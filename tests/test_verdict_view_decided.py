# -*- coding: utf-8 -*-
"""`decided_cells`：切坏/带残留（seg_defect）不算"定过字"（2026-09-20，总览/13 §一·3）。

人在卡上点「有噪声」说的是"这块图先别用"，不是"这是什么字"。此前它也算 decided，
排除名单撤了之后这些格回到待审，`skip_decided` 却把它们永远藏起来——bxgb 42 个
「已裁未放行」里 31 个从没定过字、定字台上也看不见。
"""
from __future__ import annotations

from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
from open_guji_cv.review.verdict_view import decided_cells


def _ev(key: str, kind: str, payload: dict, seq: int):
    _, pg, col, slot = key.split(":")
    return make_event("b", seq, kind,
                      EventTarget(step="seed_admit", unit="cell", key=key, book="vol01",
                                  page=int(pg), col=int(col), slot=int(slot)),
                      payload, source_format="server")


def test_seg_defect_alone_is_not_decided(tmp_path):
    log = EventLog(tmp_path)
    log.append([_ev("vol01:5:2:9", "confirm", {"v": "seg_defect", "quality": "contaminated"}, 1)])
    log.append([_ev("vol01:5:2:10", "confirm", {"v": "confirm", "shape": "復", "reading": "復"}, 2)])
    log.append([_ev("vol01:5:2:11", "confirm", {"v": "not_a_char"}, 3)])
    log.append([_ev("vol01:5:2:12", "confirm", {"v": "damaged", "guess": "塊"}, 4)])
    got = decided_cells("vol01", log)
    assert "vol01:5:2:9" not in got, "只标过切坏、没定过字的格不算裁过——它该回定字台"
    assert got == {"vol01:5:2:10", "vol01:5:2:11", "vol01:5:2:12"}


def test_seg_defect_then_confirm_is_decided(tmp_path):
    """先说切坏、后来又定了字——按最终有定字算。"""
    log = EventLog(tmp_path)
    log.append([_ev("vol01:5:2:9", "confirm", {"v": "seg_defect", "quality": "truncated"}, 1)])
    log.append([_ev("vol01:5:2:9", "confirm", {"v": "confirm", "shape": "手", "reading": "手"}, 2)])
    assert decided_cells("vol01", log) == {"vol01:5:2:9"}
