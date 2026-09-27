# -*- coding: utf-8 -*-
"""字形库抽检接口（overview#110，2026-09-27）：按来路随机抽刻例。只读，自造小库测。"""
from __future__ import annotations

import json
import sqlite3

from open_guji_cv.console.routers.glyph_spotcheck import sample_exemplars


def _db(tmp_path):
    p = tmp_path / "g.db"
    c = sqlite3.connect(p)
    c.executescript("""
      CREATE TABLE glyphs(glyph_id INTEGER, char TEXT, edition_tag TEXT);
      CREATE TABLE exemplars(instance_id TEXT, glyph_id INTEGER);
      CREATE TABLE admissions(instance_id TEXT, provenance TEXT, evidence TEXT);
    """)
    c.executemany("INSERT INTO glyphs VALUES (?,?,?)", [(1, "以", "qtw"), (2, "之", "qtw"), (3, "以", "font:x")])
    rows = []
    for i in range(30):
        iid = f"v006:1:1:{i}"
        prov, b = ("auto", "qtw-auto-20260927") if i < 20 else ("human" if i < 25 else "human_stale_x", None)
        rows.append((iid, 1 + i % 2, prov, json.dumps({"batch": b, "channel": "match_ref", "cov": .9} if b else {})))
    rows.append(("font:以", 3, "render", "{}"))
    rows.append(("v006:9:9:9", 1, "auto", json.dumps({"batch": "other"})))
    c.executemany("INSERT INTO exemplars VALUES (?,?)", [(r[0], r[1]) for r in rows])
    c.executemany("INSERT INTO admissions VALUES (?,?,?)", [(r[0], r[2], r[3]) for r in rows])
    c.execute("INSERT INTO admissions VALUES ('gone', 'auto', '{}')")     # 撤过库：不在 exemplars
    c.commit(); c.close()
    return p


def test_filter_by_provenance_and_batch(tmp_path):
    db = _db(tmp_path)
    r = sample_exemplars(db, "auto", "", 100, 0)
    assert r["n_pool"] == 21 and len(r["items"]) == 21
    assert r["batches"] == {"other": 1, "qtw-auto-20260927": 20}
    r = sample_exemplars(db, "auto", "qtw-auto-20260927", 5, 0)
    assert r["n_pool"] == 20 and len(r["items"]) == 5
    assert all(x["batch"] == "qtw-auto-20260927" and x["evidence"]["channel"] == "match_ref" for x in r["items"])


def test_human_includes_stale_and_skips_font(tmp_path):
    r = sample_exemplars(_db(tmp_path), "human", "", 100, 0)
    assert r["n_pool"] == 10
    assert all(not x["instance_id"].startswith("font:") for x in r["items"])


def test_seed_reproducible(tmp_path):
    db = _db(tmp_path)
    a = [x["instance_id"] for x in sample_exemplars(db, "auto", "", 7, 3)["items"]]
    b = [x["instance_id"] for x in sample_exemplars(db, "auto", "", 7, 3)["items"]]
    c = [x["instance_id"] for x in sample_exemplars(db, "auto", "", 7, 4)["items"]]
    assert a == b and a != c
