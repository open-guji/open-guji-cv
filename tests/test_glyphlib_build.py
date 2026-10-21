# -*- coding: utf-8 -*-
"""共享刻例库（ops.glyphlib，共享方案 S5）：按门槛精选、刻例图逐字节照搬、id 加来源前缀、借进别的书记成借来的人裁。

自造字形库，不碰真书数据。
"""
from __future__ import annotations

import hashlib
import json
import random
import sqlite3

import cv2
import pytest

from open_guji_cv.clustering.synth import degrade, synthetic_glyph


def _png(seed: int) -> bytes:
    g = degrade(synthetic_glyph(random.Random(100 + seed)), random.Random(seed), wear=0.3)
    ok, buf = cv2.imencode(".png", 255 - (g * 255).astype("uint8"))
    assert ok
    return buf.tobytes()


def _confirm(key: str, shape: str, batch: str, seq: int) -> str:
    return json.dumps({"id": f"evt_{batch}_{seq}", "batch": batch, "seq": seq, "kind": "confirm",
                       "payload": {"v": "confirm", "shape": shape, "reading": shape},
                       "target": {"key": key, "unit": "cell"}}, ensure_ascii=False)


@pytest.fixture()
def src_ws(tmp_path, monkeypatch):
    """迁过的来源书：甲 4 例（确认 3/2/2/1 个批次）、乙 1 例（2 批，但体检标了异常）、丙 1 例（2 批，近似字）、丁 1 例非人裁。"""
    from open_guji_cv.clustering.glyph_db import GlyphDB, export_store
    from open_guji_cv.core.workspace import central_data_dir
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home"))
    for k in ("GUJI_WORKSPACE", "GUJI_GLYPH_DB", "GUJI_GLYPH_STORE"):
        monkeypatch.delenv(k, raising=False)
    ws = tmp_path / "src"
    ws.mkdir()
    (ws / "workspace.yaml").write_text("id: srcbook\n", encoding="utf-8")
    (ws / ".central.json").write_text('{"ws": "srcbook", "branch": "main"}', encoding="utf-8")
    data = central_data_dir("srcbook")
    db = GlyphDB(tmp_path / "seed.sqlite")
    cells = [("甲", "human", 1), ("甲", "human", 2), ("甲", "human", 3), ("甲", "human", 4),
             ("乙", "human", 5), ("丙", "human", 6), ("丁", "align", 7)]
    try:
        for ch, prov, i in cells:
            assert db.admit_instance(f"vol01:1:{i}:1", ch, _png(i), provenance=prov, edition_tag="srced",
                                     page="1", col=i, idx=1)
        db.conn.execute("INSERT INTO approx_labels (instance_id, label, created_at) VALUES (?,?,?)",
                        ("vol01:1:6:1", "丙", "t"))
        db.conn.commit()
        export_store(db, data / "output" / "glyph_store")
    finally:
        db.close()
    ev = data / "feedback" / "events"
    ev.mkdir(parents=True)
    lines = []
    for i, batches in ((1, ["a", "b", "c"]), (2, ["a", "b"]), (3, ["a", "d", "d"]), (4, ["a"]),
                       (5, ["a", "b"]), (6, ["a", "b"])):
        ch = cells[i - 1][0]
        lines += [_confirm(f"vol01:1:{i}:1", ch, b, n) for n, b in enumerate(batches)]
    lines.append(json.dumps({"id": "evt_audit_1", "batch": "audit", "seq": 1, "kind": "glyph_audit",
                             "payload": {"instance_id": "vol01:1:5:1", "v": "evict", "flags": []},
                             "target": {"key": "vol01:1:5:1"}}))
    (ev / "h.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ws, data


def test_select_applies_thresholds(src_ws):
    from open_guji_cv.ops.glyphlib import select
    _, data = src_ws
    picked, stats = select(data / "output/glyph_store", data / "feedback/events", min_batches=2, per_char=2)
    assert [(p["instance_id"], p["batches"]) for p in picked] == [("vol01:1:1:1", 3), ("vol01:1:2:1", 2)]
    assert stats["human"] == 6 and stats["audit_or_approx"] == 2 and stats["too_few_confirms"] == 1
    picked, _ = select(data / "output/glyph_store", data / "feedback/events", min_batches=1, per_char=3)
    assert [p["instance_id"] for p in picked] == ["vol01:1:1:1", "vol01:1:2:1", "vol01:1:3:1"]  # 同一批次重复只算一次


def test_build_copies_patches_and_borrows_as_borrowed_human(src_ws, tmp_path):
    from open_guji_cv.clustering.glyph_db import rebuild_from_store
    from open_guji_cv.core.workspace import central_data_dir
    from open_guji_cv.ops.glyphlib import build
    ws, data = src_ws
    res = build(ws, "glyphlib-tst-v1", min_batches=2, per_char=3, actor="t", note="试")
    assert res["edition"] == "glyphlib-tst" and res["instances"] == 3 and res["chars"] == 1
    lib = central_data_dir("glyphlib-tst-v1")
    store = lib / "output/glyph_store"
    src_png = {hashlib.sha256(p.read_bytes()).hexdigest() for p in (data / "output/glyph_store/patches").glob("*.png")}
    lib_png = {hashlib.sha256(p.read_bytes()).hexdigest() for p in (store / "patches").glob("*.png")}
    assert len(lib_png) == 3 and lib_png <= src_png                     # 图逐字节照搬，R2 不另存
    inst = [json.loads(x) for f in (store / "instances").glob("*.jsonl") for x in f.read_text("utf-8").splitlines()]
    assert sorted(r["instance_id"] for r in inst) == ["srcbook:vol01:1:1:1", "srcbook:vol01:1:2:1",
                                                      "srcbook:vol01:1:3:1"]
    assert {r["source_id"] for r in inst} == {"srcbook.vol01"}
    ev = [json.loads(x) for x in (lib / "feedback/promote.jsonl").read_text("utf-8").splitlines()]
    assert len(ev) == 3 and ev[0]["kind"] == "promote" and ev[0]["payload"]["from_ws"] == "srcbook"

    db = tmp_path / "borrower.sqlite"                                   # 别的书借它：记成借来的人裁，不当本书铁证
    rebuild_from_store(data / "output/glyph_store", db, extra_stores=[store])
    c = sqlite3.connect(db)
    try:
        st = dict(c.execute("SELECT label_status, COUNT(*) FROM instances WHERE instance_id LIKE 'srcbook:%' "
                            "GROUP BY 1").fetchall())
    finally:
        c.close()
    assert st == {"borrowed_human": 3}


def test_build_refuses_bad_name_and_empty_selection(src_ws):
    from open_guji_cv.ops.glyphlib import build
    ws, _ = src_ws
    with pytest.raises(SystemExit, match="glyphlib-"):
        build(ws, "qkp-v1")
    with pytest.raises(SystemExit, match="一张刻例都没选出"):
        build(ws, "glyphlib-tst-v1", min_batches=9)


def test_edition_of():
    from open_guji_cv.ops.glyphlib import edition_of
    assert edition_of("glyphlib-qkp-v1") == "glyphlib-qkp" and edition_of("glyphlib-qkp-v12") == "glyphlib-qkp"
    assert edition_of("glyphlib-odd") == "glyphlib-odd"
