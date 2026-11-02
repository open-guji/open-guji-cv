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
    siku = _store(tmp_path, "siku", "book-a",
                  [("v2:vol01:1:1:1", "以"), ("v2:vol01:1:1:2", "取"), ("vol01:2:1:3", "今")])
    qtw = _store(tmp_path, "qtw", "book-b",
                 [("v2:v006:5:1:1", "以"), ("v2:v006:5:1:2", "令")])
    return siku, qtw


def test_borrowed_merge_keeps_editions_apart(two, tmp_path):
    siku, qtw = two
    out = rebuild_from_store(qtw, tmp_path / "m.db", extra_stores=[siku])
    assert out["borrowed_instances"] == 3
    db = GlyphDB(tmp_path / "m.db")
    assert db.book_edition() == "book-b"          # 库的身份仍是本书
    eds = dict(db.conn.execute(
        "SELECT char || '@' || edition_tag, n_confirmed FROM glyphs").fetchall())
    assert eds == {"以@book-b": 1, "令@book-b": 1,
                   "以@book-a": 1, "取@book-a": 1, "今@book-a": 1}
    assert db.conn.execute("SELECT count(*) FROM exemplars").fetchone()[0] == 5
    # 新进的刻例归本书 edition，不归借来的
    db.admit_instance("v2:v006:6:1:1", "取", _png(7), provenance="human")
    assert db.conn.execute("SELECT count(*) FROM glyphs WHERE char='取' "
                           "AND edition_tag='book-b'").fetchone()[0] == 1
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
    assert eds == {"book-b"}
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


def test_borrowed_human_not_counted_as_own(two, tmp_path):
    """借来的人裁不算本书人裁（共享方案 S3）：人裁通道、铁证匹配器、共识计数都只见本书的。"""
    from open_guji_cv.clustering.glyph_fp import HUMAN_SQL
    from open_guji_cv.steps.glyph_match import human_confirmed_counts

    siku, qtw = two
    rebuild_from_store(qtw, tmp_path / "m.db", extra_stores=[siku])
    db = GlyphDB(tmp_path / "m.db")
    human = {r[0] for r in db.conn.execute(HUMAN_SQL)}
    assert human == {"v2:v006:5:1:1", "v2:v006:5:1:2"}
    iron = {r[0] for r in db.conn.execute(
        "SELECT instance_id FROM instances WHERE label_status='human'")}
    assert iron == human
    st = dict(db.conn.execute(
        "SELECT instance_id, label_status FROM instances WHERE instance_id LIKE '%vol01%'"))
    assert set(st.values()) == {"borrowed_human"}
    db.close()
    assert human_confirmed_counts(str(tmp_path / "m.db")) == {"以": 1, "令": 1}


def test_rebuild_with_worker_pool_equals_single_process(tmp_path, monkeypatch):
    """派生表示多进程先算、主进程按原顺序写（GUJI-647）：库里每张表与单进程重建逐行相同。"""
    import sqlite3

    from open_guji_cv.clustering import glyph_db as G
    rows = [(f"b:1:{c}:{i}", "一二三口日"[i % 5]) for c in range(1, 4) for i in range(1, 9)]
    st = _store(tmp_path, "st", "book-a", rows)

    def dump(p):
        c = sqlite3.connect(p)
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: c.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in names
                if t != "sqlite_sequence"}
    rebuild_from_store(st, tmp_path / "one.db", jobs=1)
    monkeypatch.setattr(G, "_PARALLEL_MIN", 1)
    rebuild_from_store(st, tmp_path / "pool.db", jobs=2)
    a, b = dump(tmp_path / "one.db"), dump(tmp_path / "pool.db")
    assert a["derived"] and len(a["derived"]) == 3 * len(rows)
    assert a == b


def test_export_keeps_own_instances_under_borrowed_only_source(two, tmp_path):
    """冷启动：本书库是空的，借来库的 source（v2）被记成「只属于借来库」；之后本书人裁入库的实例
    也挂在 v2 下，导出要留下它们（史記文淵閣本 2026-10-31：3,215 例被整个 source 跳过）。"""
    siku, _ = two
    empty = tmp_path / "empty.db"
    db0 = GlyphDB(empty)
    db0.set_book_edition("book-c")
    export_store(db0, tmp_path / "own0")
    db0.close()
    rebuild_from_store(tmp_path / "own0", tmp_path / "m.db", extra_stores=[siku])
    db = GlyphDB(tmp_path / "m.db")
    db.admit_instance("v2:01:3:1:1", "以", _png(5), provenance="human")
    out = tmp_path / "re"
    c = export_store(db, out)
    db.close()
    ids = {json.loads(l)["instance_id"] for f in (out / "instances").glob("*.jsonl")
           for l in open(f, encoding="utf-8")}
    assert ids == {"v2:01:3:1:1"} and c["instances"] == 1 and c["patches"] == 1
    assert not (out / "events" / "v2.jsonl").exists()        # 借来 source 的事件照旧不导
    r = rebuild_from_store(out, tmp_path / "own.db")          # 导出再重建：本书刻例在
    assert r["instances"] == 1
