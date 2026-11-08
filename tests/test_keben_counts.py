"""keben_counts：字形库刻例按来源分列（参校本属性 C1）。自造小库，不读真书数据。"""
import json
import sqlite3

from open_guji_cv.clustering import glyph_db
from open_guji_cv.clustering.keben_counts import classify, keben_breakdown, trusted_keben_counts


def _db(tmp_path, rows, borrowed=()):
    p = tmp_path / "glyph.db"
    c = sqlite3.connect(p)
    c.executescript(glyph_db._SCHEMA)
    gid = {}
    for iid, ch, st, prov, ch_ev, has in rows:
        if ch not in gid:
            c.execute("INSERT INTO glyphs(edition_tag,char,updated_at) VALUES('b',?, 't')", (ch,))
            gid[ch] = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute("INSERT INTO exemplars VALUES(?,?,'proto','t')", (gid[ch], iid))
        if has:
            c.execute("INSERT INTO instances(instance_id,source_id,page,col,idx,patch_png,label,label_status,updated_at)"
                      " VALUES(?,'s','p',1,1,x'00',?,?,'t')", (iid, ch, st))
        if prov:
            c.execute("INSERT INTO admissions VALUES(?,?,?,?,'t')",
                      (iid, ch, prov, json.dumps({"channel": ch_ev} if ch_ev else {})))
    if borrowed:
        c.execute("CREATE TABLE IF NOT EXISTS borrowed(instance_id TEXT PRIMARY KEY, store TEXT)")
        c.executemany("INSERT INTO borrowed VALUES(?,'x')", [(b,) for b in borrowed])
    c.commit(); c.close()
    return p


def test_classify():
    assert classify("human", "human", None) == "human"
    assert classify("align", None, None) == "ref"
    assert classify("borrowed_human", None, None) == "borrow"
    assert classify("auto", "auto", '{"channel":"match_ref"}') == "ref"
    assert classify("auto", "auto", {"channel": "match_solo_5b"}) == "solo"
    assert classify("auto", "auto", "{}") == "other"
    assert classify("auto", None, None) == "other"
    assert classify("human_stale_x", None, None) == "other"
    assert classify("human", "human", None, has_instance=False) == "unknown"


def test_breakdown(tmp_path):
    p = _db(tmp_path, [
        ("a1", "九", "human", "human", None, True),
        ("a2", "九", "auto", "auto", "witness3", True),
        ("a3", "九", "auto", "auto", "match_solo_5b", True),
        ("a4", "九", "borrowed_human", None, None, True),
        ("a5", "九", None, None, None, False),
        ("font:x", "九", None, None, None, False),
        ("b1", "丸", "auto", "auto", "match_solo", True),
    ])
    bd = keben_breakdown(p)
    assert bd["九"] == {"human": 1, "ref": 1, "solo": 1, "borrow": 1, "other": 0, "unknown": 1, "trusted": 2}
    assert trusted_keben_counts(p) == {"九": 2, "丸": 0}


def test_unreadable(tmp_path):
    assert keben_breakdown(tmp_path / "nope.db") == {}


def test_borrowed_auto_is_borrow(tmp_path):
    p = _db(tmp_path, [("o1", "史", "human", "human", None, True),
                       ("q1", "史", "auto", "auto", "match_ref", True)], borrowed=["q1"])
    assert keben_breakdown(p)["史"]["borrow"] == 1
    assert trusted_keben_counts(p) == {"史": 1}


def test_borrow_db(tmp_path):
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    own = _db(tmp_path / "a", [("o1", "史", "human", "human", None, True), ("o2", "記", "auto", "auto", "match_solo", True)])
    oth = _db(tmp_path / "b", [("q1", "史", "auto", "auto", "match_ref", True), ("q2", "史", "human", "human", None, True),
                               ("q3", "史", "auto", "auto", "match_solo_5b", True), ("q4", "記", "human", "human", None, True)])
    assert trusted_keben_counts(own) == {"史": 1, "記": 0}
    assert trusted_keben_counts(own, oth) == {"史": 3, "記": 0}      # 記 本书无可信刻例，不借
