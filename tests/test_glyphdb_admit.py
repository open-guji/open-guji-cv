# -*- coding: utf-8 -*-
"""审查闭环最后一环：confirm 事件 → GlyphDB 进库。

守两条：字形/释读分开写；v2 的 id 必须与 v1 分居命名空间。
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.feedback.consumers import glyphdb_admit
from open_guji_cv.feedback.events import EventTarget, make_event

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "output" / "glyph.db"
needs_db = pytest.mark.skipif(not DB.exists(), reason="需要 output/glyph.db")


def _ev(key, payload, page, col, slot):
    return (make_event("t", 1, "confirm",
                       EventTarget(step="seed_admit", unit="cell", key=key,
                                   book="vol01", page=page, col=col, slot=slot),
                       payload), None)


@needs_db
def test_shape_and_reading_land_in_different_columns(tmp_path):
    """已/巳 这类：字形进字形索引，释读进 admissions.char。

    字形层的 near_form 护栏本来就是防「形状判据自己会认错」，字形库若被
    释读污染，将来一个真刻成这形状、该读别的字的实例会错误继承这次的释读。
    """
    db = tmp_path / "g.db"
    shutil.copy(DB, db)
    r = glyphdb_admit([_ev("vol01:24:6:13",
                           {"v": "confirm", "shape": "巳", "reading": "已",
                            "conversion": 1}, 24, 6, 13)], db_path=str(db))
    if r.added == 0 and any("缓存里没有字块" in e for e in r.errors):
        pytest.skip("字块缓存里没有这一格")
    assert r.added == 1, r.errors
    c = sqlite3.connect(db)
    label, semantic = c.execute(
        "select label, semantic from instances where instance_id='v2:vol01:24:6:13'"
    ).fetchone()
    char, prov = c.execute(
        "select char, provenance from admissions where instance_id='v2:vol01:24:6:13'"
    ).fetchone()
    c.close()
    assert label == "巳", f"字形索引该存刻本的形，实际 {label}"
    assert char == "已", f"admissions.char 该存释读，实际 {char}"
    assert prov == "human"


@needs_db
def test_v2_ids_do_not_overwrite_v1_records(tmp_path):
    """v2 的 id 必须加前缀——v1 的 idx 与 v2 的 slot 差一格，撞车会改写旧记录。

    实测 vol01/24 c1：库里 `vol01:24:1:2` 是「每」，v2 的 `1:2` 是「書」，
    170 个同 id 命中里 0 个一致。
    """
    db = tmp_path / "g.db"
    shutil.copy(DB, db)
    c = sqlite3.connect(db)
    row = c.execute(
        "select char from admissions where instance_id='vol01:24:6:2'").fetchone()
    c.close()
    if row is None:
        pytest.skip("库里没有这条 v1 记录可对照")
    before = row[0]

    glyphdb_admit([_ev("vol01:24:6:2",
                       {"v": "confirm", "shape": "次", "reading": "次"},
                       24, 6, 2)], db_path=str(db))
    c = sqlite3.connect(db)
    after = c.execute(
        "select char from admissions where instance_id='vol01:24:6:2'").fetchone()[0]
    v2 = c.execute(
        "select char from admissions where instance_id='v2:vol01:24:6:2'").fetchone()
    c.close()
    assert after == before, f"v1 记录被改写了：{before} → {after}"
    assert v2 is not None and v2[0] == "次", "v2 记录没落到 v2: 命名空间"


@needs_db
def test_not_a_char_and_skip_do_not_enter_the_library(tmp_path):
    db = tmp_path / "g.db"
    shutil.copy(DB, db)
    r = glyphdb_admit([
        _ev("vol01:24:7:2", {"v": "not_a_char"}, 24, 7, 2),
        _ev("vol01:24:7:3", {"v": "skip"}, 24, 7, 3),
    ], db_path=str(db))
    assert r.added == 0 and r.skipped == 2


def test_dry_run_writes_nothing(tmp_path):
    if not DB.exists():
        pytest.skip("需要库")
    db = tmp_path / "g.db"
    shutil.copy(DB, db)
    c = sqlite3.connect(db)
    before = c.execute("select count(*) from admissions").fetchone()[0]
    c.close()
    r = glyphdb_admit([_ev("vol01:24:6:2", {"v": "confirm", "shape": "次"}, 24, 6, 2)],
                      db_path=str(db), dry_run=True)
    c = sqlite3.connect(db)
    after = c.execute("select count(*) from admissions").fetchone()[0]
    c.close()
    assert r.added == 1 and before == after
