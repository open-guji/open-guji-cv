"""拖切线（cutline）事件 → touching-cuts 金标 的链路回归。

2026-09-05：粘连格线（R2s）的理想切点金标。事件 kind=cutline，路由到
char-segmentation/touching-cuts；expected 只留切点相关字段。
"""

from __future__ import annotations

from open_guji_cv.eval.touching import pick_cases
from open_guji_cv.feedback.consumers import _expected_of
from open_guji_cv.feedback.events import EventTarget, make_event
from open_guji_cv.feedback.routes import RouteTable


def _evt(payload: dict):
    return make_event("vol01-cutline", 1, "cutline",
                      EventTarget(step="row_segment", unit="boundary", key="vol01:44:2:17",
                                  book="vol01", page=44, col=2, slot=17),
                      payload)


def test_cutline_routes_to_touching_cuts():
    e = _evt({"y": 1980, "y_old": 1986, "verdict": "moved"})
    dests = RouteTable.load().destinations(e)
    assert any(d.consumer == "gold_add" and d.shard == "char-segmentation/touching-cuts" for d in dests), dests


def test_cutline_expected_keeps_only_cut_fields():
    e = _evt({"y": 1980, "y_old": 1986, "verdict": "moved", "bi": 17, "slot_above": 17, "slot_below": 18,
              "col_h": 2449, "char_above": "官", "char_below": "道", "client_ts": 1, "dwell_ms": 900})
    ex = _expected_of(e)
    assert ex["y"] == 1980 and ex["y_old"] == 1986 and ex["verdict"] == "moved"
    assert ex["slot_above"] == 17 and ex["slot_below"] == 18 and ex["col_h"] == 2449
    assert "client_ts" not in ex and "dwell_ms" not in ex


def test_pick_cases_spreads_over_pages_and_is_deterministic():
    cases = [dict(id=f"vol01:{p}:1:{s}", page=p) for p in (44, 71, 72) for s in range(1, 41)]
    cases += [dict(id=f"vol01:15:1:{s}", page=15) for s in range(1, 3)]
    a = pick_cases(cases, 30)
    b = pick_cases(cases, 30)
    assert [c["id"] for c in a] == [c["id"] for c in b]
    by_page = {}
    for c in a:
        by_page[c["page"]] = by_page.get(c["page"], 0) + 1
    # 轮转：只有 2 条的页全进；三个大页各拿到接近 1/3，而不是一页包场
    assert by_page[15] == 2
    assert all(8 <= by_page[p] <= 10 for p in (44, 71, 72)), by_page
