"""`feedback.migrate_v1`：人裁事件历史遗留一次规整（规范 §9 T-1、T-2、T-5、F-2、F-3）。"""

from __future__ import annotations

import json

import pytest

from open_guji_cv.feedback import migrate_v1 as M
from open_guji_cv.feedback.events import EventTarget, make_event


def _raw(e, **target_override) -> dict:
    d = json.loads(json.dumps(e.model_dump(mode="json"), ensure_ascii=False))
    d["target"].update(target_override)
    return d


def _cut(batch, seq, ts, key, y):
    return make_event(batch, seq, "cutline", EventTarget(step="row_segment", unit="boundary", key=key),
                      {"y": y, "y_old": 100, "verdict": "moved"}, ts=ts)


def _jl(*rows) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows).encode("utf-8")


def _ws() -> dict[str, bytes]:
    E = "feedback/events/"
    # T-1：两条 batch=b-split 的事件写进了 b.jsonl；b-split.jsonl 自己又从 seq 1 编起
    early1 = _raw(_cut("b-split", 1, "2026-09-08T05:01:00Z", "vol01:1:1:1", 10))
    early2 = _raw(_cut("b-split", 2, "2026-09-08T05:02:00Z", "vol01:1:1:2", 20))
    own = _raw(_cut("b", 1, "2026-09-06T00:00:00Z", "vol01:2:1:1", 30))
    late1 = _raw(_cut("b-split", 1, "2026-09-08T05:09:00Z", "vol01:3:1:1", 40))
    # T-2：id 带着改名前的批次名
    col = _raw(make_event("col", 1, "band", EventTarget(step="column_warp", unit="column", key="bxgb:38:14"),
                          {"band": "clean"}, ts="2026-09-18T00:18:41Z"))
    col["id"] = "evt_col-all_000001"
    # F-2 / F-3 / T-5
    old = _raw(make_event("d", 1, "confirm", EventTarget(step="seed_admit", unit="cell", key="bxgb:3:4:2", anchor={
        "bbox": [1, 2, 3, 4], "product_key": {"step": "seed_admit", "key": "p0003", "fingerprint": "F",
                                              "row_segment": "sha-rs"}}),
        {"v": "seg_defect", "client_ts": 1788741500.438}, ts="2026-09-10T00:00:00Z"),
        book=None, page=None, col=None, slot=None)
    only_cells = _raw(make_event("d", 2, "confirm", EventTarget(step="seed_admit", unit="cell", key="bxgb:3:4:3",
                                                                anchor={"product_key": {"row_segment": "sha2"}}),
                                 {"v": "seg_defect", "client_ts": 1788741500438}, ts="2026-09-10T00:00:01Z"))
    gold_item = {"anchor": {"book": "vol01", "col": 1, "page": 3, "slot": 1,
                            "product_key": {"row_segment": "x", "step": "row_segment"}},
                 "expected": {"y": 40}, "id": "vol01:3:1:1", "source_events": ["evt_b-split_000001"]}
    gold_col = {"anchor": {"book": "bxgb"}, "expected": {"band": "clean"}, "id": "bxgb:38:14",
                "source_events": ["evt_col-all_000001"]}
    return {
        "workspace.yaml": b"id: t\n",
        E + "b.jsonl": _jl(own, early1, early2),
        E + "b-split.jsonl": _jl(late1),
        E + "col.jsonl": _jl(col),
        E + "d.jsonl": _jl(old, only_cells),
        "feedback/consumed/gold_add.jsonl": (
            '{"event": "evt_b-split_000001", "ts": "2026-09-08T05:03:00Z", "note": "b-split"}\n'
            '{"event": "evt_b-split_000002", "ts": "2026-09-08T05:03:00Z", "note": "b-split"}\n'
            '{"event": "evt_col-all_000001", "ts": "2026-09-18T00:18:41Z", "note": "col-all"}\n').encode("utf-8"),
        "feedback/verdicts/char-segmentation/touching-cuts/items.jsonl": _jl(gold_item),
        "feedback/verdicts/char-segmentation/column-warp/items.jsonl": _jl(gold_col),
        "feedback/anchors/vol02.jsonl": (json.dumps({"event": "evt_d_000009", "key": "vol02:1:1:1", "anchor": {
            "ink_bbox": [1, 2, 3, 4], "product_key": "sha-old"}}, ensure_ascii=False) + "\n").encode("utf-8"),
    }


def _events(files, path):
    return [json.loads(x) for x in files[path].decode("utf-8").splitlines()]


def test_migrate_fixes_each_legacy_class():
    before = _ws()
    m = M.migrate(before, cells_step="row_segment")
    E = "feedback/events/"
    # T-1：挪进本批次文件、整批按时间重编 1..3；早的两条 id 不变，原文件里那条改成 3
    split = _events(m.files, E + "b-split.jsonl")
    assert [(e["seq"], e["id"], e["target"]["key"]) for e in split] == [
        (1, "evt_b-split_000001", "vol01:1:1:1"), (2, "evt_b-split_000002", "vol01:1:1:2"),
        (3, "evt_b-split_000003", "vol01:3:1:1")]
    assert [e["id"] for e in _events(m.files, E + "b.jsonl")] == ["evt_b_000001"]
    # T-2
    assert _events(m.files, E + "col.jsonl")[0]["id"] == "evt_col_000001"
    # F-2 / F-3 / T-5
    old, only_cells = _events(m.files, E + "d.jsonl")
    assert (old["target"]["book"], old["target"]["page"], old["target"]["col"], old["target"]["slot"]) == ("bxgb", 3, 4, 2)
    assert old["payload"]["client_ts"] == 1788741500438
    assert old["target"]["anchor"]["product_key"] == {"step": "seed_admit", "key": "p0003", "fingerprint": "F"}
    assert old["target"]["anchor"]["cells_sha"] == {"row_segment": "sha-rs"}
    assert "product_key" not in only_cells["target"]["anchor"]
    assert only_cells["target"]["anchor"]["cells_sha"] == {"row_segment": "sha2"}
    # 记账：撞号的旧 id 还在 → 原行留着、补新 id；改名的 → 原地换
    consumed = [json.loads(x)["event"] for x in m.files["feedback/consumed/gold_add.jsonl"].decode().splitlines()]
    assert consumed == ["evt_b-split_000001", "evt_b-split_000002", "evt_col_000001", "evt_b-split_000003"]
    # 金标：按条目 id 认是哪条事件
    tc = _events(m.files, "feedback/verdicts/char-segmentation/touching-cuts/items.jsonl")[0]
    assert tc["source_events"] == ["evt_b-split_000003"]
    assert tc["anchor"]["product_key"] == {"step": "row_segment"}
    cw = _events(m.files, "feedback/verdicts/char-segmentation/column-warp/items.jsonl")[0]
    assert cw["source_events"] == ["evt_col_000001"]
    # 补锚档
    a = json.loads(m.files["feedback/anchors/vol02.jsonl"].decode())
    assert a["anchor"]["cells_sha"] == {"row_segment": "sha-old"} and "product_key" not in a["anchor"]


def test_verify_and_gold_rebuild_unchanged_and_idempotent():
    before = _ws()
    m = M.migrate(before, cells_step="row_segment")
    v = M.verify(before, m)                                  # 内部再迁一遍须为空操作
    assert v["events"] == 7 and v["field_changes"]["id"] == 2
    assert M.gold_rebuild_check(before, m)["items"] >= 3
    assert not M.migrate(m.files, "row_segment").changed(m.files)


def test_untouched_lines_keep_their_bytes():
    before = _ws()
    line = b'{"actor": "user", "batch": "q", "id": "evt_q_000001", "kind": "confirm", "payload": {"v": "skip"}, ' \
           b'"seq": 1, "target": {"book": "vol01", "col": 1, "key": "vol01:1:1:9", "page": 1, "slot": 9, ' \
           b'"step": "seed_admit", "unit": "cell"}, "ts": "2026-09-01T00:00:00Z"}\n'
    before["feedback/events/q.jsonl"] = line
    m = M.migrate(before, cells_step="row_segment")
    assert m.files["feedback/events/q.jsonl"] == line
    assert "feedback/events/q.jsonl" not in m.changed(before)


def test_verify_rejects_content_change():
    before = _ws()
    m = M.migrate(before, cells_step="row_segment")
    p = "feedback/events/d.jsonl"
    m.files[p] = m.files[p].replace(b'"seg_defect"', b'"confirm"', 1)
    with pytest.raises(AssertionError, match="payload.v"):
        M.verify(before, m)


def test_promote_file_moves_out_of_events():
    """刻例库的升格记账（kind=promote）不是人裁事件：整文件挪到 feedback/promote.jsonl，内容不动（规范 §9 F-8）。"""
    line = b'{"batch": "promote-x", "id": "evt_promote-x_000001", "kind": "promote", "seq": 1, ' \
           b'"target": {"book": null, "key": "ws:v2:vol02:1:1:1", "unit": "glyph"}, "ts": "2026-10-19T00:00:00Z"}\n'
    files = {"workspace.yaml": b"id: g\n", "feedback/events/promote.jsonl": line}
    m = M.migrate(files)
    assert m.changed(files) == ["feedback/events/promote.jsonl", "feedback/promote.jsonl"]
    assert m.files["feedback/promote.jsonl"] == line and "feedback/events/promote.jsonl" not in m.files
    assert M.verify(files, m)["events"] == 0
    assert not M.migrate(m.files).changed(m.files)
