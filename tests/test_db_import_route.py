"""`guji db import` 导完自动消费（规范 §9 F-7）：只对导入的那几条事件跑消费者，前后各 sync 一轮。"""

from __future__ import annotations

import json

from open_guji_cv import cli_db
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event


def _cut(seq: int, key: str):
    return make_event("exp-cut", seq, "cutline", EventTarget(step="row_segment", unit="boundary", key=key,
                                                             book="vol01", page=1, col=1, slot=seq),
                      {"y": 10 * seq, "y_old": 5, "verdict": "moved"}, ts=f"2026-10-21T00:00:0{seq}Z")


def _setup(tmp_path, monkeypatch):
    fb = tmp_path / "data" / "feedback"
    (fb / "events").mkdir(parents=True)
    (fb / "routes.yaml").write_text(
        "- match: {kind: cutline}\n  to:\n  - {consumer: gold_add, shard: char-segmentation/touching-cuts}\n",
        encoding="utf-8")
    EventLog(fb).append([_cut(1, "vol01:1:1:1"), _cut(2, "vol01:1:1:2")])
    calls = []
    monkeypatch.setattr(cli_db, "sync_workspace", lambda ws, **kw: calls.append(ws) or {"action": "nothing"})
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(fb))
    monkeypatch.setenv("GUJI_VERDICTS_DIR", str(fb / "verdicts"))
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path / "ws"))
    return fb, calls


def test_route_imported_consumes_only_the_imported_events(tmp_path, monkeypatch):
    monkeypatch.delenv("GUJI_DATA_BRANCH", raising=False)
    fb, calls = _setup(tmp_path, monkeypatch)
    out = cli_db.route_imported(tmp_path / "ws", {"evt_exp-cut_000002"}, branch="main")
    assert len(calls) == 2 and out["pushed"] == "nothing"
    assert EventLog(fb).consumed_ids("gold_add") == {"evt_exp-cut_000002"}
    items = [json.loads(x) for x in (fb / "verdicts/char-segmentation/touching-cuts/items.jsonl")
             .read_text(encoding="utf-8").splitlines()]
    assert [i["id"] for i in items] == ["vol01:1:1:2"]


def test_route_imported_skips_other_branch(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_DATA_BRANCH", "exp/GUJI-1-x")
    fb, calls = _setup(tmp_path, monkeypatch)
    out = cli_db.route_imported(tmp_path / "ws", {"evt_exp-cut_000001"}, branch="main")
    assert "skipped" in out and not calls and not EventLog(fb).consumed_ids("gold_add")
