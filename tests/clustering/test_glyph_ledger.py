# -*- coding: utf-8 -*-
"""字形库总账：并套口径、影子副本、字头修复。"""

from __future__ import annotations

import sqlite3

import cv2
import numpy as np
import pytest

from open_guji_cv.clustering import glyph_ledger as L
from open_guji_cv.clustering.glyph_db import GlyphDB


def _png(k: int) -> bytes:
    img = np.full((64, 64), 255, np.uint8)
    cv2.rectangle(img, (10 + k, 10), (50, 50 - k), 0, 3)
    return cv2.imencode(".png", img)[1].tobytes()


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "g.db"
    g = GlyphDB(p)
    # 机器准入（本书 bk 来源）＋ 人裁（v2 命名空间）＋ 字体
    g.admit_instance("bk:1:1:1", "甲", _png(0), provenance="align")
    g.admit_instance("bk:1:1:2", "甲", _png(1), provenance="align")
    g.admit_instance("bk:1:1:3", "乙", _png(2), provenance="match")
    g.admit_instance("v2:bk:1:1:3", "乙", _png(2), provenance="human")   # 同一格
    g.admit_instance("v2:bk:1:2:1", "丙", _png(3), provenance="human")
    g.admit_instance("font:x:丁", "丁", _png(4), provenance="render", edition_tag="font:x")
    g.conn.execute("UPDATE sources SET kind='font' WHERE source_id='font'")
    # 脏字头：拼音首字母、码位缺失
    g.conn.execute("UPDATE glyphs SET semantic='b', unicode_cp=NULL WHERE char='丙'")
    g.conn.commit()
    g.close()
    return p


def test_summary_merges_editions_and_dedupes_cells(db):
    s = L.library_summary(db)
    b = s["book"]
    assert b["chars"] == 3                       # 甲乙丙，字体的丁不算
    assert b["exemplars"] == 5 and b["cells"] == 4
    assert b["shadow_duplicates"] == 1
    assert b["provenance"] == {"align": 2, "human": 2, "match": 1}
    assert b["singleton_chars"] == 2             # 乙（两份同格）、丙
    assert b["chars_split_across_editions"] == 1  # 乙在 bk 与 v2 各一行
    assert s["store"]["ok"] is False             # 没有 store


def test_char_table_counts_cells(db):
    rows = {r["char"]: r for r in L.char_table(db)}
    assert rows["甲"]["n"] == 2 and rows["乙"]["n"] == 1
    assert "丁" not in rows


def test_repair_heads_and_shadow(db):
    rep = L.repair_glyph_heads(db, dry_run=False)
    assert rep["n"] == 1
    c = sqlite3.connect(db)
    sem, cp = c.execute("select semantic, unicode_cp from glyphs where char='丙'").fetchone()
    assert sem == "丙" and cp == ord("丙")
    c.close()
    sh = L.evict_shadow_duplicates(db, dry_run=False)
    assert sh["evicted"] == 1 and sh["ids"] == ["bk:1:1:3"]
    assert L.library_summary(db)["book"]["shadow_duplicates"] == 0


def test_admit_heals_frozen_head(db):
    """字头 semantic 首次插入即冻结；遇到非汉字旧值，下一次准入把它顶掉。"""
    c = sqlite3.connect(db)
    c.execute("UPDATE glyphs SET semantic='x', unicode_cp=NULL WHERE char='甲'")
    c.commit(); c.close()
    g = GlyphDB(db)
    g.admit_instance("bk:1:3:1", "甲", _png(5), provenance="align")
    g.close()
    c = sqlite3.connect(db)
    assert c.execute("select semantic, unicode_cp from glyphs where char='甲' "
                     "and edition_tag='bk'").fetchone() == ("甲", ord("甲"))
    c.close()


def test_v1_twin_same_cell(tmp_path):
    """v1 idx = v2 slot − 1 且形状对得上 = 同一格：机器那份撤，人裁那份留。"""
    p = tmp_path / "g.db"
    g = GlyphDB(p)
    g.admit_instance("vo:3:4:9", "即", _png(0), provenance="align")        # v1 机器，记成读法
    g.admit_instance("vo:3:4:5", "甲", _png(1), provenance="align")        # 不对应的格
    g.admit_instance("v2:vo:3:4:10", "卽", _png(0), provenance="human")   # 同一格的人裁
    ring = np.full((64, 64), 255, np.uint8)
    cv2.circle(ring, (32, 32), 20, 0, 3)
    g.admit_instance("v2:vo:3:4:6", "乙", cv2.imencode(".png", ring)[1].tobytes(),
                     provenance="human")                                  # idx 对上但形不同
    g.conn.execute("UPDATE sources SET pipeline_version='v1' WHERE source_id='vo'")
    g.conn.commit()
    g.close()
    c = sqlite3.connect(p)
    got = L.v1_shadow_duplicates(c)
    c.close()
    assert [(d["v1"], d["v2"]) for d in got] == [("vo:3:4:9", "v2:vo:3:4:10")]
    sh = L.evict_shadow_duplicates(p, dry_run=False)
    assert sh["ids"] == ["vo:3:4:9"] and len(sh["v1_conflicts"]) == 1
