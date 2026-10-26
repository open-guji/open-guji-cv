# -*- coding: utf-8 -*-
"""换图源按格级对照表改键（`ops/cell_rekey.py`，GUJI-748）：字形库实例 id、L2 表、金标 jsonl、模板库出处。

核心是**撞号**：新旧页号交错（旧 5 页 → 新 3 页，旧 3 页 → 新 1 页），改完以后 `_human_shapes` 读到的
每个键都得是新图上那一格，停放的旧实例不能再被任何「按冒号取末 4 段」的读法读回成格。"""

from __future__ import annotations

import json
import sqlite3

import cv2
import numpy as np
import pytest

from open_guji_cv.clustering.glyph_db import GlyphDB
from open_guji_cv.groups.freq import _cell_key
from open_guji_cv.ops import cell_rekey as ck
from open_guji_cv.ops.glyphlib import cell_key as glyphlib_cell_key

HEAD = "旧格\t新格\t旧字\t新字\t类别\tIoU\t说明\n"
ROWS = [
    ("vol04:3:1:1", "vol04:1:1:1", "欽", "欽", "同格", "0.88", ""),
    ("vol04:5:1:1", "vol04:3:1:1", "定", "定", "同格", "0.90", ""),     # 旧 5 页 → 新 3 页：落到旧 3 页的号上
    ("vol04:11:2:4", "vol04:9:2:3", "乾", "乾", "改号", "0.96", ""),
    ("vol04:3:6:10", "", "二", "", "删", "0.317", "新页 1 上没有 IoU≥0.5 的格"),
    ("", "vol04:1:6:10", "", "二", "新增", "", ""),
    ("vol04:3:4:7a", "vol04:1:4:7a", "湖", "湖", "同格", "0.89", ""),
]


def _png(k: int) -> bytes:
    img = np.full((64, 64), 255, np.uint8)
    cv2.rectangle(img, (10 + k, 10), (50, 50 - k), 0, 3)
    return cv2.imencode(".png", img)[1].tobytes()


@pytest.fixture
def cmap(tmp_path):
    p = tmp_path / "vol04.tsv"
    p.write_text(HEAD + "".join("\t".join(r) + "\n" for r in ROWS), encoding="utf-8")
    return ck.load_cell_map(p)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "g.db"
    g = GlyphDB(path)
    for i, (iid, ch) in enumerate([("v2:vol04:3:1:1", "欽"), ("v2:vol04:5:1:1", "定"), ("v2:vol04:11:2:4", "乾"),
                                   ("v2:vol04:3:6:10", "二"), ("v2:vol04:3:4:7a", "湖"),
                                   ("v2:vol04:200:1:1", "末"),          # 表里没有（退役页）
                                   ("v2:vol05:3:1:1", "總")]):          # 别的册，不动
        pg, col, slot = iid.split(":")[2:5]
        g.admit_instance(iid, ch, _png(i), provenance="human", page=pg, col=int(col),
                         idx=int(slot.rstrip("ab")), bbox=[1.0, 2.0, 3.0, 4.0])
    g.conn.execute("INSERT INTO approx_labels (instance_id, label, created_at) VALUES (?,?,?)",
                   ("v2:vol04:11:2:4", "乾", "2026-10-01"))
    g.conn.execute("INSERT INTO pairs (inst_a, inst_b, relation, origin, created_at) VALUES (?,?,?,?,?)",
                   ("v2:vol04:3:1:1", "v2:vol04:5:1:1", "same", "test", "2026-10-01"))
    g.conn.commit()
    g.close()
    return path


def _human(path) -> dict[str, str]:
    from open_guji_cv.clustering.glyph_fp import HUMAN_SQL
    c = sqlite3.connect(path)
    try:
        return {iid[3:]: ch for iid, ch in c.execute(HUMAN_SQL)}
    finally:
        c.close()


def test_load_cell_map(cmap):
    assert cmap.book == "vol04"
    assert cmap.move["vol04:11:2:4"] == "vol04:9:2:3"
    assert "vol04:3:6:10" in cmap.deleted
    assert "vol04:1:6:10" in cmap.new_cells
    assert cmap.counts() == {"move": 4, "renumbered": 4, "deleted": 1, "new_cells": 5}


def test_load_rejects_two_old_on_one_new(tmp_path):
    p = tmp_path / "bad.tsv"
    p.write_text(HEAD + "vol04:3:1:1\tvol04:1:1:1\t\t\t同格\t0.9\t\n"
                        "vol04:3:1:2\tvol04:1:1:1\t\t\t改号\t0.8\t\n", encoding="utf-8")
    with pytest.raises(ValueError, match="同时对上"):
        ck.load_cell_map(p)


def test_glyph_db_rekey_chain_and_park(db, cmap):
    before = _human(db)
    assert before["vol04:3:1:1"] == "欽"
    res = ck.rekey_glyph_db(db, cmap, rev=1)
    s = res["summary"]
    assert s["instances"] == 6 and s["rekey"] == 4 and s["park"] == 2
    assert s["park_by_reason"] == {"deleted": 1, "not_in_table": 1}
    h = _human(db)
    # 交错的页号：新 1 页那格是旧 3 页的「欽」，新 3 页那格是旧 5 页的「定」，不是原地留下的旧「欽」
    assert h["vol04:1:1:1"] == "欽"
    assert h["vol04:3:1:1"] == "定"
    assert h["vol04:9:2:3"] == "乾"
    assert h["vol04:1:4:7a"] == "湖"
    assert "vol04:11:2:4" not in h and "vol04:3:6:10" not in h and "vol04:5:1:1" not in h
    assert h["vol05:3:1:1"] == "總"
    c = sqlite3.connect(db)
    try:
        ids = {r[0] for r in c.execute("SELECT instance_id FROM instances")}
        assert "v2~r1~vol04~3~6~10" in ids and "v2~r1~vol04~200~1~1" in ids
        assert c.execute("SELECT page, col, idx, bbox FROM instances WHERE instance_id='v2:vol04:9:2:3'"
                         ).fetchone() == ("9", 2, 3, None)
        assert c.execute("SELECT instance_id FROM approx_labels").fetchone()[0] == "v2:vol04:9:2:3"
        assert c.execute("SELECT inst_a, inst_b FROM pairs").fetchone() == ("v2:vol04:1:1:1", "v2:vol04:3:1:1")
        assert c.execute("SELECT count(*) FROM exemplars WHERE instance_id LIKE '__rekey__%'").fetchone()[0] == 0
        ev = json.loads(c.execute("SELECT evidence FROM admissions WHERE instance_id='v2:vol04:9:2:3'"
                                  ).fetchone()[0])
        assert ev["rekeyed_from"] == "v2:vol04:11:2:4"
        reasons = dict(c.execute("SELECT instance_id, reason FROM evictions"))
        assert reasons["v2:vol04:3:6:10"].endswith("park->v2~r1~vol04~3~6~10")
        assert len(reasons) == 6
    finally:
        c.close()


def test_parked_ids_do_not_read_back_as_cells():
    """停放 id 不能被「取冒号末 4 段」「5 段去头」的读法读回成格（cv#632 A24 复核 v4 第 1 条）。"""
    pid = ck.parked_id("v2", "vol04:3:6:10", 1)
    assert ":" not in pid
    assert ck.parse_cell(_cell_key(pid)) is None
    assert ck.parse_cell(glyphlib_cell_key(pid)) is None


def test_glyph_db_second_run_refused(db, cmap):
    ck.rekey_glyph_db(db, cmap, rev=1)
    with pytest.raises(SystemExit, match="已经按"):
        ck.rekey_glyph_db(db, cmap, rev=1)


def test_dry_run_writes_nothing(db, cmap):
    before = _human(db)
    res = ck.rekey_glyph_db(db, cmap, rev=1, dry_run=True)
    assert res["summary"]["rekey"] == 4
    assert _human(db) == before


def test_v1_instances_are_parked(tmp_path, cmap):
    path = tmp_path / "g.db"
    g = GlyphDB(path)
    g.admit_instance("v1:vol04:3:1:0", "欽", _png(0), provenance="human", page="3", col=1, idx=0)
    g.close()
    res = ck.rekey_glyph_db(path, cmap, rev=7)
    assert res["rows"][0]["new"] == "v1~r7~vol04~3~1~0"
    assert res["rows"][0]["why"] == "v1_idx"


def test_verify(db, cmap):
    bad = ck.verify_glyph_db(db, cmap)
    assert not bad["ok"]                        # 改键前：旧 11:2:4、200:1:1 不在新格集合
    ck.rekey_glyph_db(db, cmap, rev=1)
    evs = [{"kind": "confirm", "ts": "2026-10-27T00:00:00Z", "payload": {"shape": "欽", "v": "confirm"},
            "target": {"book": "vol04", "key": "vol04:1:1:1"}},
           {"kind": "confirm", "ts": "2026-10-27T00:00:00Z", "payload": {"shape": "宀", "v": "confirm"},
            "target": {"book": "vol04", "key": "vol04:9:2:3"}}]
    res = ck.verify_glyph_db(db, cmap, evs)
    assert res["human_not_in_new"] == [] and res["stray_ids"] == []
    assert res["shape_mismatch"] == [("vol04:9:2:3", "乾", "宀")]
    assert not res["ok"]


def test_rekey_l2_table(tmp_path, cmap):
    p = tmp_path / "ry.json"
    p.write_text(json.dumps({"schema": "group_clf/1", "group": "ry", "cells": {
        "vol04:11:2:4": {"ctx": "v3:a|b", "char": "日"},
        "vol04:3:6:10": {"ctx": "v3:c|d", "char": "曰"},
        "vol05:1:1:1": {"ctx": "v3:e|f", "char": "日"}}}, ensure_ascii=False, indent=1), encoding="utf-8")
    res = ck.rekey_json(p, cmap)
    assert (res["move"], res["deleted"], res["other"]) == (1, 1, 1)
    d = json.loads(p.read_text(encoding="utf-8"))
    assert set(d["cells"]) == {"vol04:9:2:3", "vol05:1:1:1"}
    assert d["cells"]["vol04:9:2:3"]["ctx"] == "v3:a|b"
    assert d["rekey"][0]["dropped"] == ["vol04:3:6:10"]


def test_rekey_labels_jsonl(tmp_path, cmap):
    p = tmp_path / "labels.jsonl"
    rows = [{"id": "vol04:11:2:4", "book": "vol04", "page": 11, "col": 2, "slot": "4", "form": "乾"},
            {"id": "vol04:3:6:10", "book": "vol04", "page": 3, "col": 6, "slot": "10", "form": "二"},
            {"id": "vol07:1:1:1", "book": "vol07", "page": 1, "col": 1, "slot": "1", "form": "之"}]
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    res = ck.rekey_jsonl(p, cmap)
    assert (res["move"], res["renumbered"], res["deleted"], res["other"]) == (1, 1, 1, 1)
    kept = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]
    assert kept[0] == {"id": "vol04:9:2:3", "book": "vol04", "page": 9, "col": 2, "slot": "3", "form": "乾"}
    retired = [json.loads(ln) for ln in (tmp_path / "labels.retired.jsonl").read_text(encoding="utf-8").splitlines()]
    assert retired[0]["id"] == "vol04:3:6:10"


def test_rekey_ids_bank_keeps_parallel_lists(tmp_path, cmap):
    p = tmp_path / "ids_bank.json"
    d = {"version": 1, "group": "x", "size": 48, "templates": {},
         "source": {"books": {"甲": ["vol04", "vol04"]}, "cells": ["vol04:11:2:4", "vol04:3:6:10"],
                    "keys": ["甲", "甲"], "labels": ["甲", "甲"]}}
    p.write_text(json.dumps(d), encoding="utf-8")
    res = ck.rekey_ids_bank(p, cmap, rev=1)
    assert (res["move"], res["parked"]) == (1, 1)
    cells = json.loads(p.read_text(encoding="utf-8"))["source"]["cells"]
    assert cells == ["vol04:9:2:3", "cell~r1~vol04~3~6~10"]
