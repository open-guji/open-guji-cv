# -*- coding: utf-8 -*-
"""格级审阅（GUJI-364b，2026-10）：清单带 cands、四档裁决校验、只追加写入、TSV 导出。

自造清单与事件，全部落 tmp；不碰任何真书数据，不挂消费者（路由表不配 cell_review）。
直调端点函数（同 test_glyph_candidates），不起 TestClient。
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from open_guji_cv.console.auth import Identity
from open_guji_cv.feedback import cell_review as cr

_ID = Identity(email="cell-test@example.com", role="reviewer", tier="reviewer")

ROWS = [
    {"_meta": {"title": "格级审阅测试清单"}},
    {"cell_id": "vol01:24:3:5", "char": "仕", "cands": ["仕", "任"], "reason": "形近"},
    {"cell_id": "vol01:24:3:6", "char": "河", "cands": ["河"]},
    {"cell_id": "vol01:24:3:7a", "char": "士"},
]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from open_guji_cv.console import deps
    from open_guji_cv.console.routers import cell_review as router
    from open_guji_cv.console.routers import feedback as fb

    for key in ("feedback", "batches", "dataset"):
        monkeypatch.setitem(deps._roots, key, tmp_path / key)
    for cached in ("_log", "_batches", "_gold"):
        monkeypatch.setattr(deps, cached, None)
    d = tmp_path / "feedback" / "candidates"
    d.mkdir(parents=True)
    (d / "t1.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in ROWS) + "\n",
                                encoding="utf-8")
    return router, fb


def _post(fb, events, consume=False):
    body = {"batch": cr.batch_of("t1"), "step": cr.STEP, "unit": "cell", "kind": cr.KIND,
            "events": events, "consume": consume}
    return fb.api_events(fb.EventsIn(**body), identity=_ID)


def test_load_keeps_cands_and_reason(env, tmp_path):
    _, _ = env
    _, rows, problems = cr.load(tmp_path / "feedback" / "candidates" / "t1.jsonl")
    by = {r["cell_id"]: r for r in rows}
    assert problems == []
    assert by["vol01:24:3:5"]["cands"] == ["仕", "任"] and by["vol01:24:3:5"]["reason"] == "形近"
    assert by["vol01:24:3:7a"]["cands"] == []          # 缺省为空


def test_write_and_latest_wins(env):
    _, fb = env
    out = _post(fb, [{"id": "vol01:24:3:5", "verdict": "pick", "picked": "任", "t": 1, "client_ts": 1},
                     {"id": "vol01:24:3:6", "verdict": "none", "t": 2}])
    assert out["appended"] == 2
    assert "consumed" not in out            # 路由表不配消费者：不消费、不写定字
    _post(fb, [{"id": "vol01:24:3:5", "verdict": "unsure", "t": 3}])
    dec = cr.latest(fb.deps.event_log(), "t1")
    assert dec["vol01:24:3:5"]["verdict"] == "unsure" and dec["vol01:24:3:5"]["picked"] is None
    assert dec["vol01:24:3:6"]["verdict"] == "none"


def test_pick_must_be_candidate(env):
    _, fb = env
    with pytest.raises(HTTPException) as e:
        _post(fb, [{"id": "vol01:24:3:5", "verdict": "pick", "picked": "士", "t": 1}])
    assert e.value.status_code == 400 and "候选字" in e.value.detail


def test_pick_without_picked_rejected(env):
    _, fb = env
    with pytest.raises(HTTPException):
        _post(fb, [{"id": "vol01:24:3:5", "verdict": "pick", "t": 1}])


def test_other_single_codepoint_only(env):
    _, fb = env
    with pytest.raises(HTTPException):
        _post(fb, [{"id": "vol01:24:3:7a", "verdict": "other", "other_char": "士仕", "t": 1}])
    with pytest.raises(HTTPException):
        _post(fb, [{"id": "vol01:24:3:7a", "verdict": "other", "other_char": " ", "t": 1}])
    out = _post(fb, [{"id": "vol01:24:3:7a", "verdict": "other", "other_char": "𡈽", "t": 1}])
    assert out["appended"] == 1            # 扩展区一个码位也算一个字符


def test_pick_must_be_single_codepoint_even_without_cands(env):
    _, fb = env
    # 无候选的格（vol01:24:3:7a）：pick 仍须是单个码位
    with pytest.raises(HTTPException) as e:
        _post(fb, [{"id": "vol01:24:3:7a", "verdict": "pick", "picked": "士仕", "t": 1}])
    assert e.value.status_code == 400 and "单个码位" in e.value.detail
    with pytest.raises(HTTPException):
        _post(fb, [{"id": "vol01:24:3:7a", "verdict": "pick", "picked": " ", "t": 1}])
    # 有候选的格：多字同样拒
    with pytest.raises(HTTPException):
        _post(fb, [{"id": "vol01:24:3:5", "verdict": "pick", "picked": "仕任", "t": 1}])
    out = _post(fb, [{"id": "vol01:24:3:7a", "verdict": "pick", "picked": "士", "t": 1}])
    assert out["appended"] == 1            # 无候选的格，单字 pick 合法


def test_unknown_cell_and_wrong_batch_rejected(env):
    _, fb = env
    with pytest.raises(HTTPException):
        _post(fb, [{"id": "vol09:1:1:1", "verdict": "none", "t": 1}])
    body = {"batch": "candidates-t1", "step": cr.STEP, "unit": "cell", "kind": cr.KIND,
            "events": [{"id": "vol01:24:3:6", "verdict": "none", "t": 1}], "consume": False}
    with pytest.raises(HTTPException):
        fb.api_events(fb.EventsIn(**body), identity=_ID)


def test_tsv_rows_match_list_and_format(env, tmp_path):
    router, fb = env
    _post(fb, [{"id": "vol01:24:3:5", "verdict": "pick", "picked": "仕", "t": 1, "reviewer": None},
               {"id": "vol01:24:3:7a", "verdict": "other", "other_char": "士", "note": "多字\n换行\t制表", "t": 2}])
    resp = router.api_cell_review_tsv("t1")
    text = resp.body.decode("utf-8")
    assert text.startswith("﻿")
    lines = text[1:].splitlines()
    assert lines[0].split("\t") == list(cr.TSV_COLUMNS)
    body = [ln.split("\t") for ln in lines[1:]]
    assert len(body) == 3                                   # 行数 = 清单行数（含未裁的格）
    assert [r[0] for r in body] == sorted(r[0] for r in body)
    by = {r[0]: r for r in body}
    assert by["vol01:24:3:5"][7] == "pick" and by["vol01:24:3:5"][8] == "仕"
    assert by["vol01:24:3:6"][7] == ""                      # 未裁：verdict 空
    assert by["vol01:24:3:7a"][5] == "a" and by["vol01:24:3:7a"][9] == "士"
    assert by["vol01:24:3:7a"][10] == "多字 换行 制表"        # 制表符与换行不进单元格
    # 同批次重复导出结果一致
    assert router.api_cell_review_tsv("t1").body == resp.body


def test_review_view_tallies(env):
    router, fb = env
    _post(fb, [{"id": "vol01:24:3:5", "verdict": "pick", "picked": "仕", "t": 1},
               {"id": "vol01:24:3:6", "verdict": "none", "t": 2}])
    view = router.api_cell_review("t1")
    assert view["tally"] == {"pick": 1, "none": 1, "unsure": 0, "other": 0, "todo": 1}
    assert [c["cell_id"] for c in view["cells"]] == sorted(c["cell_id"] for c in view["cells"])


@pytest.fixture()
def http(env):
    """HTTP 层：确认 `.tsv` 路由能解析（不被 JSON 路由吃掉）、校验失败回 400、清单不存在回 404。"""
    from fastapi.testclient import TestClient

    from open_guji_cv.console import auth as console_auth
    from open_guji_cv.console.app import app
    app.dependency_overrides[console_auth.get_identity] = lambda: _ID
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_http_tsv_and_json_routes(http):
    r = http.get("/api/cell-review/t1.tsv")
    assert r.status_code == 200 and r.text.startswith("﻿")
    assert r.headers["content-disposition"] == 'attachment; filename="cell-review-t1.tsv"'
    j = http.get("/api/cell-review/t1")
    assert j.status_code == 200 and len(j.json()["cells"]) == 3
    assert http.get("/api/cell-review/nope.tsv").status_code == 404


def test_http_post_validation_codes(http):
    base = {"batch": "cellreview-t1", "step": cr.STEP, "unit": "cell", "kind": cr.KIND, "consume": False}
    bad = {**base, "events": [{"id": "vol01:24:3:5", "verdict": "pick", "picked": "士", "t": 1}]}
    assert http.post("/api/events", json=bad).status_code == 400
    ok = {**base, "events": [{"id": "vol01:24:3:5", "verdict": "none", "t": 1}]}
    r = http.post("/api/events", json=ok)
    assert r.status_code == 200 and r.json()["appended"] == 1
