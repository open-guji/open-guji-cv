# -*- coding: utf-8 -*-
"""字形库 × 工作区记录对账（H 人裁单写者任务书件 3）：excluded / verdict / pipeline 三档。

原脚本 `scripts/glyph_crosscheck.py`（cv `b162e64`）的口径挪进
`clustering/glyph_ledger.py::crosscheck()`，这里补一份此前没有的单测——
脚本形态没法 import 着测，函数形态可以。
"""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from open_guji_cv.clustering import glyph_ledger as L
from open_guji_cv.clustering.glyph_db import GlyphDB


def _png(k: int) -> bytes:
    img = np.full((32, 32), 255, np.uint8)
    cv2.rectangle(img, (4 + k, 4), (28, 28 - k), 0, 2)
    return cv2.imencode(".png", img)[1].tobytes()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    return ws


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "g.db"
    g = GlyphDB(p)
    g.admit_instance("v2:bk:1:1:1", "甲", _png(0), provenance="human")   # 会被排除名单命中
    g.admit_instance("v2:bk:1:1:2", "乙", _png(1), provenance="human")   # 会被改判事件命中
    g.admit_instance("v2:bk:1:1:3", "丙", _png(2), provenance="human")   # 没问题
    g.admit_instance("bk:1:1:4", "丁", _png(3), provenance="align")      # 机器准入，会被 seed_admit 撤回
    g.admit_instance("bk:1:1:5", "戊", _png(4), provenance="match")      # 机器准入，没问题
    g.close()
    return p


def test_crosscheck_flags_excluded_verdict_and_pipeline(workspace, db):
    (workspace / "config").mkdir(parents=True)
    (workspace / "config" / "crop_exclusions.jsonl").write_text(
        json.dumps({"instance_id": "bk:1:1:1", "origin": "human", "reason": "not_a_char",
                   "note": "重看是界行残留"}, ensure_ascii=False) + "\n",
        encoding="utf-8")

    ev_dir = workspace / "feedback" / "events"
    ev_dir.mkdir(parents=True)
    (ev_dir / "b.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in [
        {"id": "evt_b_1", "ts": "2099-01-01T00:00:00Z", "batch": "b", "seq": 1, "actor": "user",
         "kind": "confirm", "target": {"step": "s", "unit": "cell", "key": "bk:1:1:2"},
         "payload": {"v": "confirm", "shape": "改"}},
    ]) + "\n", encoding="utf-8")

    admit_dir = workspace / "products" / "bk" / "seed_admit"
    admit_dir.mkdir(parents=True)
    (admit_dir / "p0001.json").write_text(json.dumps({"seed_admit": {"columns": [
        {"chars": [{"id": "bk:1:1:4", "admit": False, "char": "丁", "channel": "align",
                    "doubts": ["low_conf"]},
                   {"id": "bk:1:1:5", "admit": True, "char": "戊", "channel": "match"}]}]}},
        ensure_ascii=False), encoding="utf-8")

    res = L.crosscheck(db, book="bk")
    assert res["n_lib"] == 5
    by_cell = {f["cell"]: f for f in res["findings"]}
    assert by_cell["bk:1:1:1"]["check"] == "excluded" and by_cell["bk:1:1:1"]["why"] == "not_a_char"
    assert by_cell["bk:1:1:2"]["check"] == "verdict" and by_cell["bk:1:1:2"]["why"] == "latest:改"
    assert by_cell["bk:1:1:4"]["check"] == "pipeline" and by_cell["bk:1:1:4"]["why"] == "no_longer_admitted"
    assert "bk:1:1:3" not in by_cell and "bk:1:1:5" not in by_cell  # 没问题的两条不报
    assert res["counts"] == {"excluded": 1, "verdict": 1, "pipeline": 1}
    assert res["drift_missing"] is None                             # 没跑 --drift


def test_crosscheck_filters_by_book(workspace, db):
    res_other = L.crosscheck(db, book="other-book")
    assert res_other["n_lib"] == 5 and res_other["findings"] == []
