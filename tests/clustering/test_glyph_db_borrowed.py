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


# ---- 借法：scope=human 与钉号记号（借库参照方案缺口 1、2，2026-11-05）----

def _mixed_store(tmp_path):
    """被借库里有人裁和机器入库两种来源。"""
    db = GlyphDB(tmp_path / "mix.db")
    db.set_book_edition("book-m")
    db.admit_instance("v2:v009:1:1:1", "以", _png(0), provenance="human")
    db.admit_instance("v2:v009:1:1:2", "取", _png(1), provenance="match")
    db.admit_instance("v2:v009:1:1:3", "令", _png(2), provenance="align")
    out = tmp_path / "mix"
    export_store(db, out)
    db.close()
    return out


def test_scope_human_borrows_only_human_instances(two, tmp_path):
    from open_guji_cv.clustering.glyph_db import borrowed_store
    _, qtw = two
    mix = _mixed_store(tmp_path)
    full = rebuild_from_store(qtw, tmp_path / "all.db", extra_stores=[mix])
    assert full["borrowed_instances"] == 3
    only = rebuild_from_store(qtw, tmp_path / "h.db", extra_stores=[borrowed_store(mix, "human")])
    assert only["borrowed_instances"] == 1
    db = GlyphDB(tmp_path / "h.db")
    ids = {r[0] for r in db.conn.execute("SELECT instance_id FROM borrowed")}
    assert ids == {"v2:v009:1:1:1"}
    # 借来的刻例跟着实例走：机器入库的字没有刻例
    ex = {r[0] for r in db.conn.execute("SELECT instance_id FROM exemplars")}
    assert "v2:v009:1:1:2" not in ex and "v2:v009:1:1:1" in ex
    assert db.conn.execute("SELECT count(*) FROM derived WHERE instance_id='v2:v009:1:1:2'").fetchone()[0] == 0
    db.close()


def test_scope_human_without_admissions_refused(two, tmp_path):
    """被借库没有准入台账就分不出人裁：报错，不静默借成空库。"""
    from open_guji_cv.clustering.glyph_db import borrowed_store
    _, qtw = two
    mix = _mixed_store(tmp_path)
    (mix / "admissions.jsonl").unlink()
    with pytest.raises(ValueError, match="admissions"):
        rebuild_from_store(qtw, tmp_path / "x.db", extra_stores=[borrowed_store(mix, "human")])


def test_borrowed_store_rejects_bad_scope(tmp_path):
    from open_guji_cv.clustering.glyph_db import borrowed_store
    with pytest.raises(ValueError, match="scope"):
        borrowed_store(tmp_path, "some")


def _stores(db_path):
    db = GlyphDB(db_path)
    try:
        return {r[0] for r in db.conn.execute("SELECT DISTINCT store FROM borrowed")}
    finally:
        db.close()


def test_default_borrow_keeps_store_string(two, tmp_path):
    """缺省借法（借全部、不钉）：borrowed.store 与此前逐字相同，glyph_match 的 borrow_fingerprint 不变。"""
    from open_guji_cv.clustering.glyph_db import borrowed_store
    siku, qtw = two
    rebuild_from_store(qtw, tmp_path / "a.db", extra_stores=[siku])
    rebuild_from_store(qtw, tmp_path / "b.db", extra_stores=[borrowed_store(siku)])
    assert _stores(tmp_path / "a.db") == _stores(tmp_path / "b.db") == {str(siku)}


def test_borrow_fingerprint_follows_scope_and_pin(tmp_path):
    """借法记号进库名（借库参照方案缺口 1、2）：`glyph_match.borrow_fingerprint` 不改代码就跟着变；
    钉的摘要变了指纹就变，缺省借法只有库名。"""
    import shutil

    from open_guji_cv.clustering.glyph_db import borrowed_store
    from open_guji_cv.steps.glyph_match import _borrow_name, borrow_fingerprint
    root = tmp_path / ".borrowed" / "lib-b@g3" / "output" / "glyph_store"
    lender = _mixed_store(tmp_path)
    shutil.copytree(lender, root)
    own = _store(tmp_path, "own", "book-o", [("v2:v001:1:1:1", "以")])
    names = {}
    for tag, spec in {"plain": borrowed_store(root), "human": borrowed_store(root, "human"),
                      "pin": borrowed_store(root, "human", "glyph-1a2b"),
                      "pin2": borrowed_store(root, "human", "glyph-9999")}.items():
        db = tmp_path / f"{tag}.db"
        rebuild_from_store(own, db, extra_stores=[spec])
        names[tag] = borrow_fingerprint(db)
    assert names["plain"] == "lib-b@g3"
    assert names["human"] == "lib-b@g3#human"
    assert names["pin"] == "lib-b@g3#human~glyph-1a2b"
    assert len(set(names.values())) == 4
    assert _borrow_name(next(iter(_stores(tmp_path / "pin.db")))) == "lib-b@g3#human~glyph-1a2b"


def test_borrowed_label_without_standard_layout(tmp_path):
    from open_guji_cv.clustering.glyph_db import borrowed_label
    assert borrowed_label(tmp_path / "some_store") == str(tmp_path / "some_store")
    assert borrowed_label(tmp_path / "some_store", "human").endswith("some_store#human")


def test_scope_human_plus_auto_takes_vision_confirmed_auto(two, tmp_path):
    """human+auto（全唐文 11-05 提）：人裁加「看图确认过」的自动刻例；没确认的机器入库、证据坏掉的不借。"""
    from open_guji_cv.clustering.glyph_db import borrowed_store
    _, qtw = two
    db = GlyphDB(tmp_path / "lend2.db")
    db.set_book_edition("book-l2")
    db.admit_instance("v2:v009:1:1:1", "以", _png(0), provenance="human")
    db.admit_instance("v2:v009:1:1:2", "取", _png(1), provenance="auto",
                      evidence={"batch": "b1", "confirmed": "claude_vision"})
    db.admit_instance("v2:v009:1:1:3", "令", _png(2), provenance="auto", evidence={"batch": "b2"})
    db.admit_instance("v2:v009:1:1:4", "今", _png(3), provenance="match", evidence={"confirmed": "claude_vision"})
    out = tmp_path / "lend2"
    export_store(db, out)
    db.close()
    for scope, want in (("human", {"v2:v009:1:1:1"}),
                        ("human+auto", {"v2:v009:1:1:1", "v2:v009:1:1:2"})):
        rebuild_from_store(qtw, tmp_path / f"{scope}.db", extra_stores=[borrowed_store(out, scope)])
        d = GlyphDB(tmp_path / f"{scope}.db")
        assert {r[0] for r in d.conn.execute("SELECT instance_id FROM borrowed")} == want
        d.close()
    from open_guji_cv.steps.glyph_match import borrow_fingerprint
    assert borrow_fingerprint(tmp_path / "human+auto.db") == "lend2#human+auto"
    assert borrowed_store(out, "human+auto").scope == "human+auto"
