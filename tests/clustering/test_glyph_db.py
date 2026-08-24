"""GlyphDB 跨书字形数据库测试。"""

import json

import numpy as np
import pytest

from open_guji_cv.clustering.extractor import load_index
from open_guji_cv.clustering.feedback import append_event
from open_guji_cv.clustering.glyph_db import GlyphDB, K_MIN
from open_guji_cv.clustering.review.state import ReviewSession


@pytest.fixture()
def db(tmp_path):
    d = GlyphDB(tmp_path / "glyphdb.sqlite")
    yield d
    d.close()


def _prepare_labels(synth_book):
    """合成书上补反馈：确认最大两簇 + 一个 impure 标记（幂等：只写一次）。"""
    s = ReviewSession(synth_book)
    ordered = sorted(s.clusters.values(), key=lambda c: -c["size"])
    big, second = ordered[0], ordered[1]
    lp = s.labels_path
    if not s.state.cluster_labels:                    # module 级共享，防重复追加
        append_event(lp, {"op": "confirm", "cluster": big["cluster_id"],
                          "char": "甲", "members": big["members"]})
        append_event(lp, {"op": "confirm", "cluster": second["cluster_id"],
                          "char": "乙", "members": second["members"]})
        if len(ordered) > 2 and ordered[2]["size"] >= 2:
            append_event(lp, {"op": "flag",
                              "cluster": ordered[2]["cluster_id"],
                              "flag": "impure",
                              "members": ordered[2]["members"]})
    return big, second


def test_import_book_populates_tables(db, synth_book):
    big, _ = _prepare_labels(synth_book)
    summary = db.import_book(synth_book, edition_tag="ed1",
                             source_meta={"collection": "測試叢書",
                                          "script_style": "宋體刻"})
    assert summary["instances"] == 36
    assert summary["labeled"] >= big["size"]
    assert summary["glyphs"] == 2                     # 甲、乙
    st = db.stats()
    assert st["instances"] == 36
    assert st["pairs"].get("same", 0) > 0
    cur = db.conn.cursor()
    row = cur.execute("SELECT collection, script_style, edition_tag "
                      "FROM sources").fetchone()
    assert row == ("測試叢書", "宋體刻", "ed1")
    # 派生物齐备：norm + 骨架 + 特征
    kinds = {k for (k,) in cur.execute("SELECT DISTINCT kind FROM derived")}
    assert kinds == {"norm", "skeleton", "feat_hog"}
    # 语义与码位
    ch, cp = cur.execute("SELECT char, unicode_cp FROM glyphs "
                         "WHERE char='甲'").fetchone()
    assert cp == ord("甲")


def test_import_idempotent(db, synth_book):
    _prepare_labels(synth_book)
    s1 = db.import_book(synth_book, edition_tag="ed1")
    s2 = db.import_book(synth_book, edition_tag="ed1")
    assert s2["events_new"] == 0                      # 事件冪等
    assert s2["pairs_new"] == 0                       # 对冪等
    st = db.stats()
    assert st["instances"] == 36                      # 无重复行


def test_exemplar_cap_and_min(db, synth_book):
    big, _ = _prepare_labels(synth_book)
    db.import_book(synth_book, edition_tag="ed1", k_max=4)
    cur = db.conn.cursor()
    for (gid, char, status, n_conf) in cur.execute(
            "SELECT glyph_id, char, status, n_confirmed FROM glyphs"):
        n_ex = cur.execute("SELECT COUNT(*) FROM exemplars WHERE glyph_id=?",
                           (gid,)).fetchone()[0]
        assert n_ex <= 4                              # 上限
        assert n_ex >= min(n_conf, 1)
        if n_conf < K_MIN:
            assert status == "sparse"
        roles = {r for (r,) in cur.execute(
            "SELECT role FROM exemplars WHERE glyph_id=?", (gid,))}
        assert "medoid" in roles                      # 必有代表


def test_impure_flag_becomes_diff_pairs(db, synth_book):
    _prepare_labels(synth_book)
    db.import_book(synth_book, edition_tag="ed1")
    st = db.stats()
    s = ReviewSession(synth_book)
    if s.state.cluster_flags:                         # 合成书有 ≥3 个多成员簇时
        assert st["pairs"].get("diff", 0) > 0


def test_query_hits_confirmed_char(db, synth_book):
    big, _ = _prepare_labels(synth_book)
    db.import_book(synth_book, edition_tag="ed1")
    # 用确认簇一个成员的归一化图/特征查询
    npz = np.load(synth_book / "phase5_clusters" / "features.npz")
    pos = {i.id: k for k, i in
           enumerate(load_index(synth_book / "phase4_chars"))}
    k = pos[big["members"][0]]
    hits = db.query(npz["patches"][k], edition_hint="ed1")
    assert hits and hits[0].char == "甲"
    assert hits[0].f1 > 0.6
    # 异版提示查不到（分域隔离）
    assert db.query(npz["patches"][k], edition_hint="other") == []


def test_export_rebuild_roundtrip(db, synth_book, tmp_path):
    """导出到 Git 友好目录 → 重建 SQLite，知识与检索能力完全保留。"""
    from open_guji_cv.clustering.glyph_db import (export_store,
                                                  rebuild_from_store)
    big, _ = _prepare_labels(synth_book)
    db.import_book(synth_book, edition_tag="ed1",
                   source_meta={"collection": "測試叢書"})
    before = db.stats()

    store = tmp_path / "store"
    exported = export_store(db, store)
    assert exported["glyphs"] == 2 and exported["patches"] >= 2
    # 只导出已标注/代表实例的图，未标注的不进真源
    assert exported["instances"] < before["instances"]
    assert (store / "glyphs.jsonl").exists()
    assert (store / "README.md").exists()

    rebuilt = rebuild_from_store(store, tmp_path / "new.sqlite")
    assert rebuilt["glyphs"] == before["glyphs"]
    assert rebuilt["pairs"] == before["pairs"]
    assert rebuilt["exemplars"] == before["exemplars"]
    assert rebuilt["events"] == before["events"]

    # 重建后仍能检索命中
    from open_guji_cv.clustering.glyph_db import GlyphDB
    db2 = GlyphDB(tmp_path / "new.sqlite")
    try:
        npz = np.load(synth_book / "phase5_clusters" / "features.npz")
        pos = {i.id: k for k, i in
               enumerate(load_index(synth_book / "phase4_chars"))}
        k = pos[big["members"][0]]
        hits = db2.query(npz["patches"][k], edition_hint="ed1")
        assert hits and hits[0].char == "甲"
    finally:
        db2.close()


def test_export_is_deterministic(db, synth_book, tmp_path):
    """两次导出字节一致——否则每次提交都是无意义 diff。"""
    from open_guji_cv.clustering.glyph_db import export_store
    _prepare_labels(synth_book)
    db.import_book(synth_book, edition_tag="ed1")
    a, b = tmp_path / "a", tmp_path / "b"
    export_store(db, a)
    export_store(db, b)
    for f in sorted(a.rglob("*.jsonl")):
        assert f.read_bytes() == (b / f.relative_to(a)).read_bytes(), f.name


def test_query_cache_invalidates_on_new_glyphs(tmp_path):
    """特征矩阵常驻缓存：入库新字形后必须自动重载，不能返回陈旧结果。"""
    import numpy as np
    from open_guji_cv.clustering.glyph_db import GlyphDB

    db = GlyphDB(tmp_path / "c.sqlite")
    probe = np.zeros((64, 64), dtype=np.uint8)
    probe[20:44, 20:44] = 1
    assert db.query(probe, k=3) == []          # 空库，同时把缓存建起来

    _seed_one_glyph(db, "甲", probe)
    hits = db.query(probe, k=3)
    assert [h.char for h in hits] == ["甲"], "新入库的字形没被检索到（缓存未失效）"

    _seed_one_glyph(db, "乙", probe)
    assert {h.char for h in db.query(probe, k=5)} == {"甲", "乙"}
    db.close()


def _seed_one_glyph(db, char, norm):
    """直接塞一个 glyph+exemplar+derived，绕开 import_book 的整书依赖。"""
    from open_guji_cv.clustering.glyph_db import _now, _png
    cur = db.conn.cursor()
    iid = f"seed:{char}"
    cur.execute("INSERT OR IGNORE INTO sources (source_id, edition_tag, kind,"
                " created_at) VALUES ('seed','seed-ed','woodblock',?)", (_now(),))
    cur.execute(
        "INSERT OR REPLACE INTO instances (instance_id, source_id, page, col,"
        " idx, patch_png, updated_at) VALUES (?,'seed','p',0,0,?,?)",
        (iid, _png(norm), _now()))
    cur.execute("INSERT OR REPLACE INTO glyphs (edition_tag, char, status,"
                " n_confirmed, updated_at) VALUES ('seed-ed',?,'sparse',1,?)",
                (char, _now()))
    gid = cur.execute("SELECT glyph_id FROM glyphs WHERE char=?",
                      (char,)).fetchone()[0]
    cur.execute("INSERT OR REPLACE INTO exemplars VALUES (?,?,'medoid',?)",
                (gid, iid, _now()))
    db._write_derived(cur, iid, norm)
    db.conn.commit()
