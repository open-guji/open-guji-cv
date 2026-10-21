"""`feedback.migrate_dedupe`：删整轮重发的副本（规范 §9 O-8）。"""

from __future__ import annotations

import json

import pytest

from open_guji_cv.feedback import migrate_dedupe as D
from open_guji_cv.feedback.events import EventTarget, make_event


def _ev(batch, seq, ts, key, v, cts):
    e = make_event(batch, seq, "confirm", EventTarget(step="seed_admit", unit="cell", key=key),
                   {"v": v, "client_ts": cts}, ts=ts)
    return json.loads(json.dumps(e.model_dump(mode="json"), ensure_ascii=False))


def _jl(*rows) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows).encode("utf-8")


def _ws() -> dict[str, bytes]:
    orig = _ev("a", 1, "2026-09-10T00:00:00Z", "vol01:1:1:1", "seg_defect", 1.0)
    copy1 = _ev("b", 1, "2026-09-10T01:00:00Z", "vol01:1:1:1", "seg_defect", 1.0)
    copy2 = _ev("c", 1, "2026-09-10T02:00:00Z", "vol01:1:1:1", "seg_defect", 1.0)
    # 同格、不同 client_ts：新的一次判断，不是副本
    again = _ev("c", 2, "2026-09-10T03:00:00Z", "vol01:1:1:1", "seg_defect", 2.0)
    other = _ev("b", 2, "2026-09-10T01:00:01Z", "vol01:1:1:2", "ok", 3.0)
    gold = {"id": "vol01:1:1:1", "expected": {"v": "seg_defect"},
            "source_events": [orig["id"], copy1["id"], again["id"]]}
    return {
        "workspace.yaml": b"id: t\n",
        "feedback/events/a.jsonl": _jl(orig),
        "feedback/events/b.jsonl": _jl(copy1, other),
        "feedback/events/c.jsonl": _jl(copy2, again),
        "feedback/consumed/gold_add.jsonl": "".join(
            json.dumps({"event": i, "ts": "2026-09-11T00:00:00Z"}) + "\n"
            for i in (orig["id"], copy1["id"], copy2["id"], other["id"])).encode("utf-8"),
        "feedback/anchors/vol01.jsonl": "".join(
            json.dumps({"event": i, "key": "vol01:1:1:1"}) + "\n" for i in (orig["id"], copy1["id"])).encode("utf-8"),
        "feedback/verdicts/char-segmentation/x/items.jsonl": _jl(gold),
    }


def test_copies_map_to_the_earliest_original():
    assert D.find_copies(_ws()) == {"evt_b_000001": "evt_a_000001", "evt_c_000001": "evt_a_000001"}


def test_migrate_drops_copies_and_rewrites_references():
    before = _ws()
    m = D.migrate(before)
    assert m.files["feedback/events/a.jsonl"] == before["feedback/events/a.jsonl"]
    assert [json.loads(x)["id"] for x in m.files["feedback/events/b.jsonl"].decode().splitlines()] == ["evt_b_000002"]
    assert [json.loads(x)["id"] for x in m.files["feedback/events/c.jsonl"].decode().splitlines()] == ["evt_c_000002"]
    assert [json.loads(x)["event"] for x in m.files["feedback/consumed/gold_add.jsonl"].decode().splitlines()] == [
        "evt_a_000001", "evt_b_000002"]
    assert [json.loads(x)["event"] for x in m.files["feedback/anchors/vol01.jsonl"].decode().splitlines()] == [
        "evt_a_000001"]
    g = json.loads(m.files["feedback/verdicts/char-segmentation/x/items.jsonl"])
    assert g["source_events"] == ["evt_a_000001", "evt_c_000002"]
    assert D.verify(before, m) == {"events": 3, "dropped": 2}
    assert not D.migrate(m.files).changed(m.files)


def test_event_without_client_ts_is_never_a_copy():
    a = _ev("a", 1, "2026-09-10T00:00:00Z", "k", "ok", None)
    b = _ev("b", 1, "2026-09-10T01:00:00Z", "k", "ok", None)
    assert D.find_copies({"feedback/events/a.jsonl": _jl(a), "feedback/events/b.jsonl": _jl(b)}) == {}


def test_verify_rejects_a_changed_survivor():
    before = _ws()
    m = D.migrate(before)
    m.files["feedback/events/b.jsonl"] = m.files["feedback/events/b.jsonl"].replace(b'"ok"', b'"bad"')
    with pytest.raises(AssertionError):
        D.verify(before, m)
