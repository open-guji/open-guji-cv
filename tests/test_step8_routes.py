# -*- coding: utf-8 -*-
"""Step8 两条接口的拒绝路径（PR #13 评审补）：直接调路由函数，事件日志指到临时目录，
消费换成桩——不碰真库、真金标、真产物。"""
from __future__ import annotations

import pytest

from open_guji_cv.console import deps
from open_guji_cv.console.routers import step8 as s8
from open_guji_cv.feedback.events import EventLog


@pytest.fixture
def log(tmp_path, monkeypatch):
    lg = EventLog(tmp_path / "fb")
    monkeypatch.setattr(deps, "event_log", lambda: lg)
    import open_guji_cv.feedback.consumers as C
    monkeypatch.setattr(C, "route_and_consume", lambda *a, **k: {"results": []})
    s8._SEG_CACHE.clear()
    return lg


def _row(i, pair=("甲", "乙")):
    return {"id": f"bxgb:3:1:{i}", "pair": pair, "who": "pending", "cat": None, "fix": "",
            "basis": "", "final": pair[0], "tier": "dispute", "default_cat": "other",
            "decided_at": "", "page": 3, "col": 1, "slot": i, "sub": None,
            "hyp_ctx": "x", "ref_ctx": "y"}


def test_decide_rejects_stale_ids(log, monkeypatch):
    """前端拿的是旧队列：字位已不在这个字对里 → 拒，且一条事件都不写。"""
    monkeypatch.setattr(s8, "_load", lambda book: {"diffs": []})
    monkeypatch.setattr(s8, "_items", lambda book, doc: [_row(1), _row(2, ("丁", "戊"))])
    out = s8.api_step8_decide(s8.DecideIn(book="bxgb", pair=["甲", "乙"],
                                          ids=["bxgb:3:1:1", "bxgb:3:1:2"], who="theirs"))
    assert out["ok"] is False and "请刷新" in out["error"]
    assert log.read("bxgb-collate") == []


def test_decide_accepts_variation_selector_fix(log, monkeypatch):
    """都不对填 葛󠄀（葛 + VS17）：一个字，两个码位，要收。"""
    monkeypatch.setattr(s8, "_load", lambda book: {"diffs": []})
    monkeypatch.setattr(s8, "_items", lambda book, doc: [_row(1)])
    monkeypatch.setattr(s8, "_jiajie_of_book", lambda book: set())
    monkeypatch.setattr(s8, "_jiajie", lambda: set())
    out = s8.api_step8_decide(s8.DecideIn(book="bxgb", pair=["甲", "乙"], ids=["bxgb:3:1:1"],
                                          who="neither", fix="葛\U000E0100"))
    assert out["ok"] is True and out["final"] == "葛\U000E0100"


def test_seg_writes_once_and_validates(log):
    ok = s8.SegIn(book="bxgb", items=[s8.SegItem(id="bxgb:3:1:1", flags=["truncated"])])
    assert s8.api_step8_seg(ok)["appended"] == 1
    s8._SEG_CACHE.clear()
    assert s8.api_step8_seg(ok)["appended"] == 0, "状态没变不重写"
    assert s8.api_step8_seg(s8.SegIn(book="bxgb", items=[
        s8.SegItem(id="bxgb:3:1:1", flags=["bogus"])]))["ok"] is False
    assert s8.api_step8_seg(s8.SegIn(book="bxgb", items=[
        s8.SegItem(id="other:3:1:1", flags=[])]))["ok"] is False, "别的书的字位不收"
    evs = log.read("bxgb-collate")
    assert len(evs) == 1 and evs[0].payload["v"] == "seg_defect" and "shape" not in evs[0].payload


def test_seg_jiazhu_submits_rerun_from_row_segment_once(log, monkeypatch):
    """Step8 卡片「小注当正文」= 打回重做：事件带 reason=jiazhu_as_main，并为新勾上的页下一张从 row_segment 起的重跑单。"""
    subs = []
    monkeypatch.setattr(s8, "_submit_rerun", lambda book, pages: subs.append((book, pages)) or {"pages": pages, "job": "j1"})
    ok = s8.SegIn(book="bxgb", items=[s8.SegItem(id="bxgb:5:3:3", flags=["jiazhu"]),
                                      s8.SegItem(id="bxgb:5:4:1", flags=["jiazhu"]),
                                      s8.SegItem(id="bxgb:9:1:2", flags=["truncated"])])
    out = s8.api_step8_seg(ok)
    assert out["appended"] == 3 and out["rerun"] == {"pages": [5], "job": "j1"} and subs == [("bxgb", [5])]
    evs = {e.target.key: e.payload for e in log.read("bxgb-collate")}
    assert evs["bxgb:5:3:3"]["reason"] == "jiazhu_as_main" and evs["bxgb:5:3:3"]["quality"] == "truncated"
    assert "reason" not in evs["bxgb:9:1:2"]
    s8._SEG_CACHE.clear()
    out2 = s8.api_step8_seg(ok)                       # 状态没变：不重写、不再下单
    assert out2["appended"] == 0 and len(subs) == 1
