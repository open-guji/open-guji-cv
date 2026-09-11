"""open_guji_cv.eval.llm_online_accuracy 的拼接逻辑：日志 join 反馈事件。"""

from __future__ import annotations

import json
from pathlib import Path

from open_guji_cv.eval import llm_online_accuracy as mla
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event


def _write_log(tmp_path: Path, book: str, rows: list[dict]) -> Path:
    p = tmp_path / "llm_online_calls" / f"{book}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p.parent


def test_human_final_char_reads_shape_or_char_fallback():
    ev = make_event("b1", 1, "confirm", EventTarget(step="context_decide", key="x"),
                    payload={"shape": "甲"})
    assert mla.human_final_char(ev) == "甲"
    ev2 = make_event("b1", 2, "confirm", EventTarget(step="context_decide", key="y"),
                     payload={"char": "乙"})
    assert mla.human_final_char(ev2) == "乙"
    ev3 = make_event("b1", 3, "mark", EventTarget(step="context_decide", key="z"),
                     payload={"shape": "丙"})
    assert mla.human_final_char(ev3) is None   # 不是 confirm/relabel，不算数


def test_load_online_calls_dedupes_by_id_keeping_latest_ts(tmp_path):
    log_dir = _write_log(tmp_path, "vol01", [
        {"id": "vol01:1:1:0", "ts": "2026-09-10T00:00:00Z", "llm_parsed_char": "甲"},
        {"id": "vol01:1:1:0", "ts": "2026-09-10T01:00:00Z", "llm_parsed_char": "乙"},
    ])
    rows = mla.load_online_calls(log_dir, "vol01")
    assert len(rows) == 1
    assert rows[0]["llm_parsed_char"] == "乙"   # 更晚的那条


def test_compute_report_matches_resolved_human_verdicts(tmp_path):
    log_dir = _write_log(tmp_path, "vol01", [
        {"id": "vol01:1:1:0", "ts": "t1", "book": "vol01", "page": 1,
         "provider": "qwen", "model": "qwen-plus",
         "llm_parsed_char": "乙", "llm_answer_in_candidates": True,
         "candidates_chars": ["甲", "乙"]},
        {"id": "vol01:1:1:1", "ts": "t1", "book": "vol01", "page": 1,
         "provider": "qwen", "model": "qwen-plus",
         "llm_parsed_char": "丁", "llm_answer_in_candidates": True,
         "candidates_chars": ["丙", "丁"]},
        {"id": "vol01:1:1:2", "ts": "t1", "book": "vol01", "page": 1,
         "provider": "qwen", "model": "qwen-plus",
         "llm_parsed_char": None, "llm_answer_in_candidates": False,
         "candidates_chars": ["戊", "己"]},
        {"id": "vol01:1:1:3", "ts": "t1", "book": "vol01", "page": 1,
         "provider": "qwen", "model": "qwen-plus",
         "llm_parsed_char": "壬", "llm_answer_in_candidates": True,
         "candidates_chars": ["壬", "癸"]},   # 还没人审，不计入分母
    ])

    feedback_root = tmp_path / "feedback"
    elog = EventLog(feedback_root)
    elog.append([
        make_event("b1", 1, "confirm", EventTarget(step="context_decide", key="vol01:1:1:0"),
                  payload={"shape": "乙"}),      # LLM 答对
        make_event("b1", 2, "confirm", EventTarget(step="context_decide", key="vol01:1:1:1"),
                  payload={"shape": "丙"}),      # LLM 答错（说丁，人审是丙）
    ])

    report = mla.compute_report(log_dir, feedback_root=feedback_root)
    assert report["n_total_calls"] == 4
    assert report["n_answered_in_candidates"] == 3
    assert report["n_resolved"] == 2          # 只有前两条有人审
    assert report["n_correct"] == 1
    assert report["n_wrong"] == 1
    assert report["accuracy"] == 0.5
    assert report["wrong_examples"][0]["id"] == "vol01:1:1:1"
    assert report["by_model"]["qwen/qwen-plus"]["n"] == 2
