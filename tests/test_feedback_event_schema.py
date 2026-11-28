"""人裁事件规范（doc/formats/人裁事件规范.md）落到代码的几条：

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
