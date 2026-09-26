# -*- coding: utf-8 -*-
"""v1 旧刻例重键到现格号（scripts/glyph_v1_rekey.py）：链式平移、重复撤、人裁冲突留、留下者让出命名空间、幂等。"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from open_guji_cv.clustering import glyph_ledger as L
from open_guji_cv.clustering.glyph_db import GlyphDB, export_store, rebuild_from_store

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("glyph_v1_rekey", REPO / "scripts" / "glyph_v1_rekey.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


def _png(k: int) -> bytes:
    img = np.full((64, 64), 255, np.uint8)
    cv2.rectangle(img, (8 + k, 8), (54, 54 - k), 0, 3)
    return cv2.imencode(".png", img)[1].tobytes()


@pytest.fixture
def lib(tmp_path):
    p = tmp_path / "g.db"
    g = GlyphDB(p)
    for i, (iid, ch) in enumerate([("vol01:3:4:4", "甲"), ("vol01:3:4:5", "乙"), ("vol01:3:4:6", "丙"),
                                   ("vol01:3:4:7", "丁"), ("vol01:3:4:9", "戊"), ("vol01:3:4:11", "己"),
                                   ("vol01:3:4:13", "辛")]):
        g.admit_instance(iid, ch, _png(i), provenance="align")
    g.admit_instance("v2:vol01:3:4:10", "戊", _png(4), provenance="human")   # 与 v1 :9 同格同字
    g.admit_instance("v2:vol01:3:4:12", "庚", _png(5), provenance="human")   # 与 v1 :11 同格异字
    g.conn.execute("UPDATE sources SET pipeline_version='v1' WHERE source_id='vol01'")
    g.conn.commit()
    g.close()
    m = tmp_path / "map.jsonl"
    rows = [("vol01:3:4:4", "vol01:3:4:5", "exact", 0.999),   # 目标 id 正被一个没对上的 v1 占着
            ("vol01:3:4:5", "vol01:3:4:9", "weak", 0.80),
            ("vol01:3:4:6", "vol01:3:4:7", "exact", 0.998),   # 链式：7 自己也要挪走
            ("vol01:3:4:7", "vol01:3:4:8", "exact", 0.997),
            ("vol01:3:4:9", "vol01:3:4:10", "exact", 0.999),
            ("vol01:3:4:11", "vol01:3:4:12", "exact", 0.999),
            ("vol01:3:4:13", "vol01:3:4:13", "exact", 0.999)]  # 原地认定
    m.write_text("".join(json.dumps({"v1": a, "cell": b, "status": s, "cov": c, "label": "?"}) + "\n"
                         for a, b, s, c in rows), encoding="utf-8")
    return p, m


def _run(monkeypatch, db, m, *extra):
    monkeypatch.setenv("GUJI_GLYPH_DB", str(db))
    monkeypatch.setattr(sys, "argv", ["x", str(m), *extra])
    assert R.main() == 0


def _ids(db):
    c = sqlite3.connect(db)
    out = dict(c.execute("SELECT instance_id, label FROM instances"))
    src = dict(c.execute("SELECT instance_id, source_id FROM instances"))
    c.close()
    return out, src


def test_rekey_moves_evicts_and_keeps(lib, monkeypatch, capsys):
    db, m = lib
    _run(monkeypatch, db, m, "--dry-run")
    before, _ = _ids(db)
    assert "vol01:3:4:4" in before                        # dry-run 不改
    _run(monkeypatch, db, m)
    ids, src = _ids(db)
    assert ids["vol01:3:4:5"] == "甲" and ids["vol01:3:4:7"] == "丙" and ids["vol01:3:4:8"] == "丁"
    assert ids["vol01:3:4:13"] == "辛"                    # 原地认定，id 不变
    assert ids["v1:vol01:3:4:5"] == "乙"                  # 没对上：加 v1: 前缀，格号不动
    assert ids["v1:vol01:3:4:11"] == "己"                 # 与人裁异字：留着等人定
    assert "vol01:3:4:9" not in ids and "v1:vol01:3:4:9" not in ids   # 同格同字：重复，撤
    assert src["vol01:3:4:5"] == "vol01" and src["v1:vol01:3:4:5"] == "v1"
    c = sqlite3.connect(db)
    assert dict(c.execute("SELECT source_id, pipeline_version FROM sources")) == {
        "vol01": "v2", "v1": "v1", "v2": None}
    ev = json.loads(c.execute("SELECT evidence FROM admissions WHERE instance_id='vol01:3:4:5'").fetchone()[0])
    assert ev["rekeyed_from"] == "vol01:3:4:4"
    # 下游按来源认 v1：只剩两个带前缀的
    assert L._v1_sources(c) == {"v1:vol01:3:4:5", "v1:vol01:3:4:11"}
    assert L.cell_key("vol01:3:4:5", L._v1_sources(c)) == "vol01:3:4:5"
    c.close()
    assert L.v1_twin_ids("v2:vol01:3:4:12") == ["v1:vol01:3:4:11", "vol01:3:4:11"]


def test_rekey_idempotent_and_survives_rebuild(lib, monkeypatch, tmp_path, capsys):
    db, m = lib
    _run(monkeypatch, db, m)
    first = _ids(db)
    capsys.readouterr()
    _run(monkeypatch, db, m)
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["rekeyed_id_changed"] == 0 and out["evict_dup"] == 0 and out["keep_prefixed_now"] == 0
    assert _ids(db) == first
    g = GlyphDB(db)
    export_store(g, tmp_path / "store")
    g.close()
    rebuild_from_store(tmp_path / "store", tmp_path / "re.db")
    assert _ids(tmp_path / "re.db") == first
