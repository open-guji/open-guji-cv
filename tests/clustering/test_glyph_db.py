"""GlyphDB 跨书字形数据库测试（库数据一律用 admit_instance 直接造，见 conftest.seed_glyphs）。"""

import numpy as np
import pytest

from conftest import seed_glyphs
from open_guji_cv.clustering.canonical import to_canonical
from open_guji_cv.clustering.glyph_db import (CONFUSABLE_SAMPLE_CAP, K_MIN,
                                              GlyphDB, _unpng)
from open_guji_cv.clustering.normalize import normalize_patch


@pytest.fixture()
def db(tmp_path):
    d = GlyphDB(tmp_path / "glyphdb.sqlite")
    yield d
    d.close()


def _norm_of(db, iid):
    """库里某实例的 norm 图（查询用的探针）。"""
    (blob,) = db.conn.execute(
        "SELECT data FROM derived WHERE instance_id=? AND kind='norm'",
        (iid,)).fetchone()
    return _unpng(blob)


def _add_pairs_and_events(db):
    """库里补几条 pairs / events（导出重建要保住它们；admit_instance 不产这两张表）。"""
    cur = db.conn.cursor()
    cur.executemany("INSERT INTO pairs VALUES (?,?,?,?,?,?)", [
        ("tbook:乙:0", "tbook:甲:0", "diff", "impure_flag", "tbook", "t"),
        ("tbook:甲:0", "tbook:甲:1", "same", "confirm_same", "tbook", "t")])
    cur.executemany(
        "INSERT INTO events (source_id, batch, seq, ts, op, payload) "
        "VALUES (?,?,?,?,?,?)",
        [("tbook", "b1", 1, "t", "confirm", '{"op": "confirm"}'),
         ("tbook", "b1", 2, "t", "flag", '{"op": "flag"}')])
    db.conn.commit()


def test_admit_populates_tables(db):
    ids = seed_glyphs(db, n_each=5)
    st = db.stats()
    assert st["instances"] == 10
    cur = db.conn.cursor()
    assert cur.execute("SELECT COUNT(*) FROM glyphs").fetchone()[0] == 2
    # 派生物齐备：norm + 骨架 + 特征
    kinds = {k for (k,) in cur.execute("SELECT DISTINCT kind FROM derived")}
    assert kinds == {"norm", "skeleton", "feat_hog"}
    # 语义与码位
    ch, cp = cur.execute("SELECT char, unicode_cp FROM glyphs "
                         "WHERE char='甲'").fetchone()
    assert cp == ord("甲")
    # 审计行：每个实例一条
    assert cur.execute("SELECT COUNT(*) FROM admissions").fetchone()[0] == 10
    assert len(ids["甲"]) == 5


def test_admit_idempotent(db):
    seed_glyphs(db, n_each=3)
    again = seed_glyphs(db, n_each=3)           # 同 id 再来一遍
    assert again == {}                           # 第二次一个都没进
    assert db.stats()["instances"] == 6          # 无重复行
    (n,) = db.conn.execute("SELECT n_confirmed FROM glyphs "
                           "WHERE char='甲'").fetchone()
    assert n == 3                                # 计数没被二次入库累加


def test_exemplar_floor_and_status(db):
    seed_glyphs(db, chars=("甲", "乙"), n_each=5)
    seed_glyphs(db, chars=("丙",), n_each=2, seed=5)
    cur = db.conn.cursor()
    rows = cur.execute("SELECT glyph_id, char, status, n_confirmed "
                       "FROM glyphs").fetchall()
    assert len(rows) == 3
    for gid, char, status, n_conf in rows:
        n_ex = cur.execute("SELECT COUNT(*) FROM exemplars WHERE glyph_id=?",
                           (gid,)).fetchone()[0]
        assert n_ex >= min(n_conf, 1)            # 下限：有确认就有代表
        assert (status == "sparse") == (n_conf < K_MIN)


def test_confusable_exemplar_cap(db):
    """己/已/巳 一类字形：exemplar 累积到上限后不再增，但实例与审计照常写。"""
    n = CONFUSABLE_SAMPLE_CAP + 3
    seed_glyphs(db, chars=("己",), n_each=n)
    cur = db.conn.cursor()
    gid = cur.execute("SELECT glyph_id FROM glyphs WHERE char='己'").fetchone()[0]
    n_ex = cur.execute("SELECT COUNT(*) FROM exemplars WHERE glyph_id=?",
                       (gid,)).fetchone()[0]
    assert n_ex == CONFUSABLE_SAMPLE_CAP
    assert cur.execute("SELECT COUNT(*) FROM instances").fetchone()[0] == n
    assert cur.execute("SELECT COUNT(*) FROM admissions").fetchone()[0] == n


def test_query_hits_admitted_char(db):
    ids = seed_glyphs(db)
    probe = _norm_of(db, ids["甲"][0])
    hits = db.query(probe, edition_hint="ed1")
    assert hits and hits[0].char == "甲"
    assert hits[0].f1 > 0.6
    # 异版提示查不到（分域隔离）
    assert db.query(probe, edition_hint="other") == []


def test_export_rebuild_roundtrip(db, tmp_path):
    """导出到 Git 友好目录 → 重建 SQLite，知识与检索能力完全保留。"""
    from open_guji_cv.clustering.glyph_db import (export_store,
                                                  rebuild_from_store)
    ids = seed_glyphs(db)
    _add_pairs_and_events(db)
    before = db.stats()
    assert before["pairs"] == {"diff": 1, "same": 1}

    store = tmp_path / "store"
    exported = export_store(db, store)
    assert exported["glyphs"] == 2 and exported["patches"] >= 2
    assert exported["instances"] == before["instances"]
    assert (store / "glyphs.jsonl").exists()
    assert (store / "README.md").exists()

    rebuilt = rebuild_from_store(store, tmp_path / "new.sqlite")
    assert rebuilt["glyphs"] == before["glyphs"]
    assert rebuilt["pairs"] == before["pairs"]
    assert rebuilt["exemplars"] == before["exemplars"]
    assert rebuilt["events"] == before["events"]

    # 重建后仍能检索命中
    probe = _norm_of(db, ids["甲"][0])
    db2 = GlyphDB(tmp_path / "new.sqlite")
    try:
        hits = db2.query(probe, edition_hint="ed1")
        assert hits and hits[0].char == "甲"
    finally:
        db2.close()


def test_export_is_deterministic(db, tmp_path):
    """两次导出字节一致——否则每次提交都是无意义 diff。"""
    from open_guji_cv.clustering.glyph_db import export_store
    seed_glyphs(db)
    _add_pairs_and_events(db)
    a, b = tmp_path / "a", tmp_path / "b"
    export_store(db, a)
    export_store(db, b)
    files = sorted(a.rglob("*.jsonl"))
    assert files
    for f in files:
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


# ── 库路径 P0 §二·①：空库自检 ──────────────────────────────────────
def test_empty_db_with_nonempty_store_raises(tmp_path):
    """库路径解析错了会造成「库空真源非空」——这个状态必须报错退出，不许静默过。"""
    from open_guji_cv.clustering.glyph_db import assert_db_not_silently_empty

    db_path = tmp_path / "empty.sqlite"
    GlyphDB(db_path).close()          # 打开即建表，instances 仍是 0 行

    store = tmp_path / "store"
    (store / "instances").mkdir(parents=True)
    (store / "instances" / "src.jsonl").write_text(
        '{"instance_id": "x"}\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="字形库为空"):
        assert_db_not_silently_empty(db_path, store)


def test_empty_db_with_empty_or_missing_store_is_fine(tmp_path):
    """真源本来就没有实例（全新工作区、单测用的临时空库）不算异常。"""
    from open_guji_cv.clustering.glyph_db import assert_db_not_silently_empty

    db_path = tmp_path / "empty.sqlite"
    GlyphDB(db_path).close()

    assert_db_not_silently_empty(db_path, tmp_path / "no_such_store")   # 真源不存在

    empty_store = tmp_path / "empty_store"
    (empty_store / "instances").mkdir(parents=True)
    assert_db_not_silently_empty(db_path, empty_store)                 # 真源没有 jsonl


def test_nonempty_db_never_raises_regardless_of_store(tmp_path):
    """库里已经有数据就不该报——自检只管「空库」这一种状态。"""
    from open_guji_cv.clustering.glyph_db import assert_db_not_silently_empty

    db_path = tmp_path / "g.sqlite"
    db = GlyphDB(db_path)
    seed_glyphs(db, n_each=2)
    db.close()

    assert_db_not_silently_empty(db_path, tmp_path / "no_such_store")


def _seed_one_glyph(db, char, norm):
    """直接塞一个 glyph+exemplar+derived，直接造库数据。"""
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
