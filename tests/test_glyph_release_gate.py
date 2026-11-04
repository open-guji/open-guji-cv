# -*- coding: utf-8 -*-
"""字形库出版护栏（`ops/glyph_release_gate`）：多字头实例、人裁归错字头、同图人裁给了不同字，出 g<N>／glyphlib 前拒出。

自造字形库，不碰真书数据、不连网。
"""
from __future__ import annotations

import random

import cv2
import pytest

from open_guji_cv.clustering.synth import degrade, synthetic_glyph


def _png(seed: int) -> bytes:
    g = degrade(synthetic_glyph(random.Random(500 + seed)), random.Random(seed), wear=0.3)
    ok, buf = cv2.imencode(".png", 255 - (g * 255).astype("uint8"))
    assert ok
    return buf.tobytes()


def _db(path, cells):
    """cells: (实例号, 字, provenance, 图种子[, shape])"""
    from open_guji_cv.clustering.glyph_db import GlyphDB
    db = GlyphDB(path)
    try:
        for c in cells:
            iid, ch, prov, seed = c[:4]
            shape = c[4] if len(c) > 4 else None
            assert db.admit_instance(iid, ch, _png(seed), provenance=prov, edition_tag="ted",
                                     page="1", col=seed, idx=1, shape=shape)
        db.conn.commit()
    finally:
        db.close()
    return path


def _sql(path, q, args=()):
    import sqlite3
    with sqlite3.connect(path) as c:
        c.execute(q, args)


def test_clean_library_passes(tmp_path):
    from open_guji_cv.ops.glyph_release_gate import check
    p = _db(tmp_path / "g.db", [("v:1:1:1", "甲", "human", 1), ("v:1:2:1", "乙", "align", 2)])
    res = check(p)
    assert res["ok"] and res["multi_glyph"]["n"] == res["human_misfiled"]["n"] == res["human_dup"]["n"] == 0


def test_instance_under_two_glyphs_is_caught(tmp_path):
    """史記 g1 那种：人裁改对了，旧字头下的刻例没撤。"""
    from open_guji_cv.ops.glyph_release_gate import check, enforce
    p = _db(tmp_path / "g.db", [("v:1:1:1", "甲", "human", 1), ("v:1:2:1", "乙", "human", 2)])
    _sql(p, "INSERT INTO exemplars SELECT (SELECT glyph_id FROM glyphs WHERE char='乙'), 'v:1:1:1', 'seed', 'x'")
    res = check(p)
    assert not res["ok"] and res["multi_glyph"]["n"] == 1
    assert res["multi_glyph"]["sample"][0]["instance"] == "v:1:1:1"
    assert res["human_misfiled"]["n"] == 1                     # 甲的人裁实例挂在乙下面，也算归错
    with pytest.raises(SystemExit, match="护栏没过"):
        enforce(p)
    assert enforce(p, waive="试验")["waived"] == "试验"


def test_same_image_two_human_labels_is_caught(tmp_path):
    from open_guji_cv.ops.glyph_release_gate import check
    p = _db(tmp_path / "g.db", [("v:1:1:1", "甲", "human", 1), ("v:2:1:1", "乙", "human", 1)])
    res = check(p)
    assert res["human_dup"]["n"] == 1 and set(res["human_dup"]["sample"][0]["instances"]) == {"v:1:1:1", "v:2:1:1"}


def test_reading_shape_split_is_not_a_conflict(tmp_path):
    """己已巳：释读写 admissions.char，字形按刻形入库（shape），两者不同是设计，不报。"""
    from open_guji_cv.ops.glyph_release_gate import check
    p = _db(tmp_path / "g.db", [("v:1:1:1", "已", "human", 1, "巳")])
    assert check(p)["ok"]


def test_borrowed_instances_not_blocking(tmp_path):
    from open_guji_cv.ops.glyph_release_gate import check
    p = _db(tmp_path / "g.db", [("b:1:1:1", "甲", "human", 1), ("b:1:2:1", "乙", "human", 2)])
    _sql(p, "INSERT INTO exemplars SELECT (SELECT glyph_id FROM glyphs WHERE char='乙'), 'b:1:1:1', 'seed', 'x'")
    _sql(p, "CREATE TABLE borrowed (instance_id TEXT PRIMARY KEY, store TEXT)")
    _sql(p, "INSERT INTO borrowed VALUES ('b:1:1:1', 'other'), ('b:1:2:1', 'other')")
    res = check(p)
    assert res["ok"] and res["borrowed_multi_glyph"] == 1


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    from open_guji_cv.clustering.glyph_db import GlyphDB, export_store
    for k in ("GUJI_GLYPH_DB", "GUJI_GLYPH_STORE", "GUJI_PRODUCTS_DIR", "GUJI_DATA_BRANCH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GUJI_DATA_CACHE", str(tmp_path / "blobcache"))
    w = tmp_path / "ws"
    (w / "output").mkdir(parents=True)
    (w / "workspace.yaml").write_text("id: tws\n", encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", str(w))
    live = _db(w / "output" / "glyph.db", [("v2:vol01:1:1:1", "甲", "human", 1), ("v2:vol01:1:2:1", "乙", "human", 2)])
    db = GlyphDB(live)
    try:
        export_store(db, w / "output" / "glyph_store")
    finally:
        db.close()
    return w


def test_snapshot_records_gate_and_refuses_dirty_library(ws):
    from open_guji_cv.clustering.glyph_db import GlyphDB, export_store
    from open_guji_cv.core.glyph_pin import load_manifest, pinned_db_path, versions
    from open_guji_cv.ops.glyph_snapshot import snapshot
    out = snapshot(ws)
    assert out["gate"]["ok"] and load_manifest(ws, 1)["gate"]["ok"]
    live = ws / "output" / "glyph.db"
    _sql(live, "INSERT INTO exemplars SELECT (SELECT glyph_id FROM glyphs WHERE char='乙'), 'v2:vol01:1:1:1', 'seed', 'x'")
    db = GlyphDB(live)
    try:
        export_store(db, ws / "output" / "glyph_store")
    finally:
        db.close()
    with pytest.raises(SystemExit, match="出 g2护栏没过"):
        snapshot(ws)
    assert versions(ws) == [1] and not pinned_db_path(2).exists()      # 没过护栏不留清单、不留库
    out = snapshot(ws, gate_waive="试验")
    assert out["pin"] == 2 and load_manifest(ws, 2)["gate"]["waived"] == "试验"
