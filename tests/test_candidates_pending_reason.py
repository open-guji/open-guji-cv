# -*- coding: utf-8 -*-
"""候选清单的待审原因 pending_reason：行上优先，其次 _meta，缺省与认不出都记 unknown。"""
import json

from open_guji_cv.feedback import candidates as cand


def _write(tmp_path, lines):
    p = tmp_path / "x.jsonl"
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")
    return p


def test_row_then_meta_then_unknown(tmp_path):
    p = _write(tmp_path, [
        {"cell_id": "vol01:1:1:1", "char": "甲", "pending_reason": "recheck"},
        {"cell_id": "vol01:1:1:2", "char": "乙"},
        {"_meta": {"title": "t", "pending_reason": "lib_sparse_agree"}},   # _meta 写在后面也算
    ])
    meta, rows, problems = cand.load_list(p)
    assert [r["pending_reason"] for r in rows] == ["recheck", "lib_sparse_agree"]
    assert problems == []


def test_missing_and_bad_values(tmp_path):
    p = _write(tmp_path, [
        {"cell_id": "vol01:1:1:1", "char": "甲"},
        {"cell_id": "vol01:1:1:2", "char": "乙", "pending_reason": "Bad Value"},
    ])
    _, rows, problems = cand.load_list(p)
    assert [r["pending_reason"] for r in rows] == ["unknown", "unknown"]
    assert len(problems) == 1 and "Bad Value" in problems[0]


def test_unlisted_value_passes_through_for_reader_to_parse(tmp_path):
    from open_guji_cv.review.pending_reason import parse
    p = _write(tmp_path, [{"cell_id": "vol01:1:1:1", "char": "甲", "pending_reason": "future_reason"}])
    _, rows, _ = cand.load_list(p)
    assert rows[0]["pending_reason"] == "future_reason"
    assert parse(rows[0]["pending_reason"]).value == "unknown"
