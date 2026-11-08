"""keben_counts：字形库刻例按来源分列（参校本属性 C1）。自造小库，不读真书数据。"""
import json
import sqlite3

from open_guji_cv.clustering import glyph_db
from open_guji_cv.clustering.keben_counts import classify, keben_breakdown, trusted_keben_counts


def _db(tmp_path, rows):
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
