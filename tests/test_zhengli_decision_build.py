# -*- coding: utf-8 -*-
"""scripts/zhengli/decision_build.py（GUJI-652 从 ai-team 迁入）：自造 char／pending／事件，不碰真书与中心库。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "zhengli" / "decision_build.py"
spec = importlib.util.spec_from_file_location("zhengli_decision_build", SCRIPT)
db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(db)

CELLS = [
    {"a": "1:1:1", "c": "□", "lacuna": True},     # 阙文、无人裁 → ①（整理本字当候选）
    {"a": "1:1:2", "c": "乎"},                     # 待审、无人裁 → ①
    {"a": "1:1:3", "c": "也", "lacuna": True},    # 最新人裁 seg_defect → ②
    {"a": "1:1:4", "c": "者"},                     # 待审，人裁已定成现字，但在 pending 里 → 仍 ①
    {"a": "1:2:1", "c": "矣", "lacuna": True},    # 人裁已定字、不在待审 → 不收
    {"a": "1:2:2", "c": "焉"},                     # 不阙不待审 → 不收
    {"a": "1:10:1", "c": "哉", "lacuna": True},   # 无候选 → 不写、退出码 2
]


def ev(cell, payload, ts, actor="user", kind="confirm", book="vol01"):
    return json.dumps({"kind": kind, "actor": actor, "ts": ts, "target": {"key": f"{book}:{cell}"},
                       "payload": payload}, ensure_ascii=False)


def make_inputs(tmp_path: Path, with_nocand: bool = True):
    cells = CELLS if with_nocand else CELLS[:-1]
    char = {"book_id": "96mid1ogzk", "volume": 1,
            "pages": [{"page": 1, "columns": [{"cells": cells}]}]}
    pend = {"rev": "001-r1", "cells": [
        {"cell": "1:1:2", "lib_top": [{"c": "乎", "s": 0.95}, {"c": "平", "s": 0.81234}]},
        {"cell": "1:1:4", "lib_top": [{"c": "着", "s": 0.5}]},
    ]}
    events = tmp_path / "events"
    events.mkdir()
    (events / "a.jsonl").write_text("\n".join([
        ev("1:1:3", {"v": "ok", "shape": "也"}, "2026-10-01T00:00:00"),
        ev("1:1:3", {"v": "seg_defect", "quality": "truncated"}, "2026-10-02T00:00:00"),
        ev("1:2:1", {"v": "ok", "shape": "矣"}, "2026-10-01T00:00:00"),
        ev("1:1:4", {"v": "ok", "shape": "者"}, "2026-10-01T00:00:00"),
        ev("1:1:1", {"v": "seg_defect"}, "2026-10-03T00:00:00", actor="machine"),   # 非用户，不算
        ev("1:1:1", {"v": "seg_defect"}, "2026-10-03T00:00:00", book="vol02"),       # 别册，不算
        "{坏行",
        "",
    ]) + "\n", encoding="utf-8")
    tsv = tmp_path / "align.tsv"
    tsv.write_text("cell\tcur\tref\n1:1:1[x]\t□\t天\n1:1:3\t也\t地\n1:1:4\t者\t者\n", encoding="utf-8")
    (tmp_path / "001.char.json").write_text(json.dumps(char, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "001.pending.json").write_text(json.dumps(pend, ensure_ascii=False), encoding="utf-8")
    return events, tsv


def run(tmp_path, events, tsv, out):
    return db.main(["--char", str(tmp_path / "001.char.json"), "--pending", str(tmp_path / "001.pending.json"),
                    "--events-dir", str(events), "--book", "vol01", "--align-tsv", str(tsv), "--out", str(out)])


def test_two_classes_split_and_sorted(tmp_path):
    events, tsv = make_inputs(tmp_path, with_nocand=False)
    out = tmp_path / "001.decision.json"
    assert run(tmp_path, events, tsv, out) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["$schema"] == db.SCHEMA and doc["book_id"] == "96mid1ogzk" and doc["volume"] == 1
    items = {it["cell"]: it for it in doc["items"]}
    assert [it["cell"] for it in doc["items"]] == ["1:1:1", "1:1:2", "1:1:3", "1:1:4"]

    a = items["1:1:1"]
    assert a["kind"] == "uncertain" and a["status"] == "open" and a["note"] == "阙文"
    assert a["cands"] == [{"text": "天", "src": "align_ref", "why": "整理本对齐"}]
    assert "reason" not in a and "route" not in a

    assert items["1:1:2"]["note"] == "待审"
    assert items["1:1:2"]["cands"] == [{"text": "平", "src": "cv", "conf": 0.8123, "why": "字形库匹配"}]

    seg = items["1:1:3"]
    assert (seg["reason"], seg["route"], seg["route_ref"]) == ("seg_bad", "list", "GUJI-588")
    assert "truncated" in seg["note"]
    assert seg["cands"] == [{"text": "地", "src": "align_ref", "why": "整理本对齐"}]

    # 整理本字＝现字不当候选
    assert [c["text"] for c in items["1:1:4"]["cands"]] == ["着"]
    assert "1:2:1" not in items and "1:2:2" not in items


def test_no_candidate_cells_skipped_and_exit_2(tmp_path):
    events, tsv = make_inputs(tmp_path)
    out = tmp_path / "001.decision.json"
    assert run(tmp_path, events, tsv, out) == 2
    cells = [it["cell"] for it in json.loads(out.read_text(encoding="utf-8"))["items"]]
    assert "1:10:1" not in cells and len(cells) == 4                 # 文件照写，缺的格不在


def test_route_ref_override(tmp_path):
    events, tsv = make_inputs(tmp_path, with_nocand=False)
    out = tmp_path / "d.json"
    db.main(["--char", str(tmp_path / "001.char.json"), "--events-dir", str(events), "--book", "vol01",
             "--align-tsv", str(tsv), "--route-ref", "GUJI-999", "--out", str(out)])
    items = {it["cell"]: it for it in json.loads(out.read_text(encoding="utf-8"))["items"]}
    assert items["1:1:3"]["route_ref"] == "GUJI-999"
    assert "1:1:2" not in items                                        # 不给 pending：只收阙文


def test_user_verdicts_takes_latest_user_confirm(tmp_path):
    events, _ = make_inputs(tmp_path)
    v = db.user_verdicts(str(events), "vol01")
    assert v["1:1:3"] == {"v": "seg_defect", "quality": "truncated"}
    assert "1:1:1" not in v


def test_align_chars_from_align_dir_with_sub(tmp_path):
    d = tmp_path / "align_ref"
    d.mkdir()
    (d / "p0001.json").write_text(json.dumps({"align_ref": {"chars": [
        {"id": "vol01:1:1:1", "align_char": "天"},
        {"id": "vol01:1:1:3", "sub": "a", "align_char": "地"},
        {"id": "vol01:1:1:5a", "sub": "a", "align_char": "玄"},
        {"id": "vol01:1:1:6", "align_char": ""},
    ]}}, ensure_ascii=False), encoding="utf-8")
    assert db.align_chars(str(d), None, "vol01") == {"1:1:1": "天", "1:1:3a": "地", "1:1:5a": "玄"}
