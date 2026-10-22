# -*- coding: utf-8 -*-
"""排除名单与绑定核对（GUJI-659）：重切后旧人裁排除不再默默挡着新格。"""
from __future__ import annotations

import json

from open_guji_cv.clustering.exclusions import load_exclusions
from open_guji_cv.feedback.exclusion_check import stale_by_binding


def _write(p, rows):
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def test_stale_by_binding(tmp_path):
    p = tmp_path / "ex.jsonl"
    _write(p, [
        {"instance_id": "vol02:1:1:1", "origin": "human", "reason": "not_text", "source_event": "e1"},
        {"instance_id": "vol02:1:1:2", "origin": "human", "reason": "damaged", "source_event": "e2"},
        {"instance_id": "vol02:1:1:3", "origin": "human", "reason": "not_text", "source_event": "e3"},
        {"instance_id": "vol02:1:1:4", "origin": "human", "reason": "not_text"},
        {"instance_id": "vol02:1:1:5", "origin": "gate", "reason": "not_text", "source_event": "e5"},
        {"instance_id": "vol03:1:1:1", "origin": "human", "reason": "not_text", "source_event": "e6"},
    ])
    load_exclusions.cache_clear()
    b = {"e1": {"status": "valid", "bound": "vol02:1:1:1"},
         "e2": {"status": "void", "bound": None},
         "e3": {"status": "rebound", "bound": "vol02:1:1:4"},
         "e5": {"status": "void", "bound": None}}
    got = stale_by_binding("vol02", b, p)
    assert [(x["instance_id"], x["status"], x["now"]) for x in got] == [
        ("vol02:1:1:2", "void", None), ("vol02:1:1:3", "rebound", "vol02:1:1:4")]
