# -*- coding: utf-8 -*-
"""书级库借库（`rebuild_from_store(extra_stores=...)`，2026-09-27 全唐文）：
本书库 + 借来的四庫库装进同一个索引供匹配；两书 edition 分开；导出只导本书的。"""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from open_guji_cv.clustering.glyph_db import GlyphDB, export_store, rebuild_from_store


def _png(k: int) -> bytes:
    img = np.full((64, 64), 255, np.uint8)
    cv2.rectangle(img, (8 + k, 8), (54, 54 - k), 0, 3)
    return cv2.imencode(".png", img)[1].tobytes()


def _store(tmp_path, name, edition, rows):
    db = GlyphDB(tmp_path / f"{name}.db")
    db.set_book_edition(edition)
    for i, (iid, ch) in enumerate(rows):
        db.admit_instance(iid, ch, _png(i), provenance="human")
    out = tmp_path / name
    export_store(db, out)
    db.close()
    return out


@pytest.fixture
def two(tmp_path):
    siku = _store(tmp_path, "siku", "siku-zongmu",
                  [("v2:vol01:1:1:1", "以"), ("v2:vol01:1:1:2", "取"), ("vol01:2:1:3", "今")])
    qtw = _store(tmp_path, "qtw", "qtw-jiaqing",
                 [("v2:v006:5:1:1", "以"), ("v2:v006:5:1:2", "令")])
    return siku, qtw


def test_borrowed_merge_keeps_editions_apart(two, tmp_path):
    siku, qtw = two
    out = rebuild_from_store(qtw, tmp_path / "m.db", extra_stores=[siku])
    assert out["borrowed_instances"] == 3
    db = GlyphDB(tmp_path / "m.db")
    assert db.book_edition() == "qtw-jiaqing"          # 库的身份仍是本书
    eds = dict(db.conn.execute(
        "SELECT char || '@' || edition_tag, n_confirmed FROM glyphs").fetchall())
    assert eds == {"以@qtw-jiaqing": 1, "令@qtw-jiaqing": 1,
                   "以@siku-zongmu": 1, "取@siku-zongmu": 1, "今@siku-zongmu": 1}
    assert db.conn.execute("SELECT count(*) FROM exemplars").fetchone()[0] == 5
    # 新进的刻例归本书 edition，不归借来的
    db.admit_instance("v2:v006:6:1:1", "取", _png(7), provenance="human")
    assert db.conn.execute("SELECT count(*) FROM glyphs WHERE char='取' "
                           "AND edition_tag='qtw-jiaqing'").fetchone()[0] == 1
    db.close()


def test_export_from_merged_skips_borrowed(two, tmp_path):
    siku, qtw = two
    rebuild_from_store(qtw, tmp_path / "m.db", extra_stores=[siku])
    db = GlyphDB(tmp_path / "m.db")
    db.admit_instance("v2:v006:6:1:1", "取", _png(7), provenance="human")
    out = tmp_path / "re"
    c = export_store(db, out)
    db.close()
    assert c["instances"] == 3 and c["admissions"] == 3 and c["exemplars"] == 3
    eds = {json.loads(l)["edition_tag"] for l in open(out / "glyphs.jsonl", encoding="utf-8")}
    assert eds == {"qtw-jiaqing"}
    ids = {json.loads(l)["instance_id"] for f in (out / "instances").glob("*.jsonl")
           for l in open(f, encoding="utf-8")}
    assert ids == {"v2:v006:5:1:1", "v2:v006:5:1:2", "v2:v006:6:1:1"}
    assert not list((out / "patches").glob("*vol01*"))
    meta = [json.loads(l)["key"] for l in open(out / "meta.jsonl", encoding="utf-8")]
    assert meta == ["book_edition"]
    # 导出再重建（不带借库）= 纯本书库
    r = rebuild_from_store(out, tmp_path / "own.db")
    assert r["instances"] == 3 and "borrowed_instances" not in r


def test_same_edition_refused(two, tmp_path):
    siku, qtw = two
    with pytest.raises(ValueError, match="同 edition"):
        rebuild_from_store(qtw, tmp_path / "m.db", extra_stores=[qtw])


def test_plain_rebuild_unchanged(two, tmp_path):
    """不带借库时与原行为一致：没有 borrowed 表，导出不受影响。"""
    siku, _ = two
    r = rebuild_from_store(siku, tmp_path / "s.db")
    assert "borrowed_instances" not in r and r["instances"] == 3
    db = GlyphDB(tmp_path / "s.db")
    assert not db.conn.execute("SELECT 1 FROM sqlite_master WHERE name='borrowed'").fetchone()
    assert export_store(db, tmp_path / "s2")["instances"] == 3
    db.close()
