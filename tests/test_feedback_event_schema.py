"""人裁事件规范（doc/formats/裁定事件规范.md）落到代码的几条：

- 「后到覆盖」一律按 `replay_key` = (ts, batch, seq)，不按批次名；
- `target.book/page/col/slot` 全空时构造事件就从 key 补（写入口统一；老数据 10-21 已迁）；
- `resolve` 能按 kind/unit 过滤（切线与定字 key 同形）；
- 控制台写入 `client_ts` 一律毫秒；
- `guji events lint` 的几类问题。
"""

from __future__ import annotations

import json

from open_guji_cv.feedback.events import Event, EventLog, EventTarget, make_event, replay_key
from open_guji_cv.gold.store import GoldStore


def _cut(batch, seq, ts, y):
    return make_event(batch, seq, "cutline",
                      EventTarget(step="row_segment", unit="boundary", key="vol02:5:8:14"),
                      {"y": y, "y_old": 100, "verdict": "moved"}, ts=ts)


def _confirm(batch, seq, ts, shape, key="vol02:5:8:14"):
    return make_event(batch, seq, "confirm", EventTarget(step="seed_admit", unit="cell", key=key),
                      {"v": "confirm", "shape": shape}, ts=ts)


def test_replay_key_is_time_first_not_batch_name():
    # 批次名 H-… 排在 vol02-… 前面，但它是后写的更正
    old = _confirm("vol02-1-10-decide", 1, "2026-09-06T00:00:00Z", "己")
    fix = _confirm("H-fix", 1, "2026-10-01T00:00:00Z", "已")
    assert max([old, fix], key=lambda e: e.order) is old          # 旧口径：批次名序，取错
    assert max([old, fix], key=replay_key) is fix


def test_resolve_time_order_and_kind_filter(tmp_path):
    log = EventLog(tmp_path / "feedback")
    log.append([_confirm("vol02-decide", 1, "2026-09-06T00:00:00Z", "甲")])
    log.append([_confirm("H-fix", 1, "2026-10-01T00:00:00Z", "乙")])
    log.append([_cut("vol02-cutline", 1, "2026-10-02T00:00:00Z", 90)])     # 同 key 的切线
    assert log.resolve()["vol02:5:8:14"].kind == "cutline"
    got = log.resolve(kinds=("confirm",), unit="cell")["vol02:5:8:14"]
    assert got.payload["shape"] == "乙"


def test_pending_in_time_order(tmp_path):
    log = EventLog(tmp_path / "feedback")
    log.append([_confirm("zz-early", 1, "2026-09-01T00:00:00Z", "甲")])
    log.append([_confirm("aa-late", 1, "2026-10-01T00:00:00Z", "乙")])
    assert [e.batch for e in log.pending("gold_add")] == ["zz-early", "aa-late"]


def test_target_fields_filled_from_key_when_all_empty():
    raw = {"id": "evt_b_000001", "ts": "2026-09-17T00:00:00Z", "batch": "b", "seq": 1,
           "kind": "confirm", "payload": {"v": "confirm", "shape": "曾"},
           "target": {"step": "seed_admit", "unit": "cell", "key": "bxgb:3:4:2",
                      "book": None, "page": None, "col": None, "slot": None}}
    t = Event.model_validate_json(json.dumps(raw)).target
    assert (t.book, t.page, t.col, t.slot) == ("bxgb", 3, 4, 2)
    col = EventTarget(step="row_segment", unit="column", key="headcol:vol02:101:6")
    assert (col.book, col.page, col.col, col.slot) == ("vol02", 101, 6, None)


def test_target_fields_not_overwritten_and_instance_keys_left_alone():
    t = EventTarget(step="s", unit="cell", key="vol01:1:2:3", book="vol01", page=9)
    assert (t.page, t.col) == (9, None)                     # 有值不动
    g = EventTarget(step="glyph_audit", unit="cell", key="v2:vol02:132:8:17")
    assert g.book is None                                   # 刻例 id 不是格键


def test_written_events_pass_the_json_schema(tmp_path):
    """`formats/guji_feedback_event_v1.schema.json` 收得下 `EventLog.append` 写出来的行。"""
    from pathlib import Path

    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).resolve().parents[1] / "formats" /
                         "guji_feedback_event_v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    v = Draft202012Validator(schema)
    log = EventLog(tmp_path / "feedback")
    log.append([_confirm("b", 1, "2026-10-01T00:00:00Z", "之"), _cut("c", 1, "2026-10-01T00:00:00Z", 9)])
    for f in sorted((tmp_path / "feedback" / "events").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            assert not list(v.iter_errors(json.loads(line)))
    bad = json.loads(json.dumps(_confirm("b", 2, "2026-10-01T00:00:00Z", "之").model_dump(mode="json")))
    del bad["payload"]["v"]
    assert list(v.iter_errors(bad))                      # confirm 必带 payload.v


def test_auto_source_not_human():
    """book_lib_auto 的机器刻例确认（source=auto）不当人裁，不进绑定表（全唐文 r11 挪格误绑）。"""
    from open_guji_cv.feedback.events import EventTarget, counts_as_human, make_event
    t = EventTarget(step="seed_admit", unit="cell", key="005:1:1:2")
    assert not counts_as_human(make_event("b", 1, "confirm", t, {"v": "confirm", "shape": "宫", "source": "auto"}, actor="model"))
    assert counts_as_human(make_event("b", 2, "confirm", t, {"v": "confirm", "char": "宫"}))


def test_event_level_batches():
    """2026-11-26 GM4 批量规则：先认 payload.level；actor=model 无 level 的按批次名 `~` 前缀查 9 个人授意批次，
    其余算 ai。ai 仍是钉（counts_as_pin，产物不变），但不算人裁（counts_as_human）。"""
    from open_guji_cv.feedback.events import (Event, EventTarget, counts_as_human, counts_as_pin,
                                              event_level)
    t = EventTarget(step="seed_admit", unit="cell", key="02:1:1:2")

    def ev(batch, actor="model", **p):
        return Event(id=f"evt_{batch}_1", batch=batch, seq=1, ts="2026-11-01T00:00:00Z", kind="confirm",
                     target=t, payload={"v": "confirm", "shape": "公", **p}, actor=actor)
    assert event_level(ev("r52-ctx2-2rounds")) == "ai"
    assert event_level(ev("r77-重绑")) == event_level(ev("SJ-歲暫歸一-1125~u")) == "human"
    assert event_level(ev("r52-ctx2-2rounds", level="human")) == "human"
    assert event_level(ev("r77-重绑", level="ai")) == "ai"
    assert event_level(ev("L-r2-sheet", actor="user")) == "human"
    assert event_level(ev("x", source="vision")) is None
    a = ev("r59-ctx2")
    assert counts_as_pin(a) and not counts_as_human(a)
    assert counts_as_pin(ev("x", actor="user")) and counts_as_human(ev("x", actor="user"))
    assert not counts_as_pin(ev("x", source="auto"))


# ── 裁定事件来源三字段（2026-11-27，计划 1.6）────────────────────────────────

def _prov(**p):
    return make_event("b-prov", 1, "confirm", EventTarget(step="seed_admit", unit="cell", key="vol02:5:8:14"),
                      {"v": "confirm", "shape": "甲", **p}, ts="2026-11-27T00:00:00Z")


def test_missing_provenance_reports_fields():
    from open_guji_cv.feedback.events import missing_provenance
    assert missing_provenance(_prov()) == ["level", "by", "channel"]
    assert missing_provenance(_prov(level="human", by="a@b.c", channel="console")) == []
    assert missing_provenance(_prov(level="human", by="a@b.c")) == ["channel"]
    assert missing_provenance(_prov(level="robot", by="x", channel="console")) == ["level"]
    assert missing_provenance(_prov(level="ai", by="x", channel="fax")) == ["channel"]
    cut = make_event("b", 1, "cutline", EventTarget(step="row_segment", unit="boundary", key="vol02:5:8:14"), {"y": 1})
    assert missing_provenance(cut) == []        # 只对格上的 confirm 要求


def test_append_warns_but_does_not_reject_missing_provenance(tmp_path, caplog):
    import logging
    log = EventLog(tmp_path / "feedback")
    with caplog.at_level(logging.WARNING, logger="open_guji_cv.feedback.events"):
        n = log.append([_prov()])
    assert n == 1 and log.provenance_missing == 1
    assert any("缺来源字段" in r.message for r in caplog.records)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="open_guji_cv.feedback.events"):
        log.append([make_event("b-prov2", 1, "confirm", EventTarget(step="seed_admit", unit="cell", key="vol02:5:8:15"),
                               {"v": "confirm", "shape": "乙", "level": "human", "by": "a@b.c", "channel": "console"})])
    assert log.provenance_missing == 0 and not caplog.records


def test_machine_level_is_not_a_pin():
    from open_guji_cv.feedback.events import counts_as_human, counts_as_pin, event_level
    e = _prov(level="machine", by="auto_admit", channel="script")
    assert event_level(e) is None and not counts_as_pin(e) and not counts_as_human(e)
    assert event_level(_prov(level="ai", by="claude-x", channel="llm")) == "ai"


def test_schema_accepts_and_checks_provenance_fields(tmp_path):
    import pytest
    pytest.importorskip("jsonschema")
    from pathlib import Path
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).resolve().parents[1] / "formats" /
                         "guji_feedback_event_v1.schema.json").read_text(encoding="utf-8"))
    v = Draft202012Validator(schema)
    row = _prov(level="ai", by="claude-x", channel="llm").model_dump(mode="json")
    assert not list(v.iter_errors(row))
    for bad in ({"level": "robot"}, {"channel": "fax"}, {"by": ""}):
        r = _prov(level="ai", by="claude-x", channel="llm").model_dump(mode="json")
        r["payload"].update(bad)
        assert list(v.iter_errors(r)), bad
