# -*- coding: utf-8 -*-
"""审查闭环最后一环：confirm 事件 → GlyphDB 进库。

守两条：字形/释读分开写；v2 的 id 必须与 v1 分居命名空间。

2026-09-20 重写：原先五条都 `shutil.copy` **本机那份真字形库**，再在
vol01 dev_set 的产物里捞一个「还没进过库」的字位来写——库是活的，捞得到
捞不到全看这次人裁进了多少，捞不到就 skip；库不在（云端）则五条全 skip。
`_free_key()` 那个函数本身就是这套依赖的症状：它存在的唯一理由是「真库会
随人裁不断长大，写死某个 id 迟早撞上已进库的」。

现在库从**空的**建起（`GlyphDB` 打开即建表），字块由 fixture 那张冻结真页
现跑 Step1→Step4 产出。要对照 v1 旧记录就自己往库里插一条 v1 的——比在真库
里翻一条出来可控得多，也不会因为别人清了库就整条失效。
"""

from __future__ import annotations

import sqlite3

import pytest

import open_guji_cv.steps  # noqa: F401
from helpers import run_keben_from_raw
from open_guji_cv.feedback.consumers import glyphdb_admit
from open_guji_cv.feedback.events import EventTarget, make_event

BOOK, PAGE = "keben", 1


@pytest.fixture
def lib(tmp_path, monkeypatch, ws, fixture_page):
    """一个空字形库 + 一页真字块。返回 `(库路径, [(页, 列, 格), …])`。"""
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.core.book import load_book

    ctx, out = run_keben_from_raw(tmp_path, monkeypatch, book=load_book(BOOK),
                                  gray=fixture_page)
    cells = []
    for cc in out["char_index"].columns:
        if not cc.ok:
            continue
        for ch in cc.chars:
            if ch.cell_type == "char" and ch.patch_key and not ch.sub:
                if ctx.cache.get(BOOK, "char_patch", ch.patch_key) is not None:
                    cells.append((PAGE, cc.col, ch.slot))
    assert len(cells) > 10, f"冻结样页只切出 {len(cells)} 个可用字块"

    db = tmp_path / "g.db"
    GlyphDB(db).close()          # 打开即建表，instances 仍是 0 行
    return db, cells


def _ev(key, payload, page, col, slot, book: str = BOOK):
    return (make_event("t", 1, "confirm",
                       EventTarget(step="seed_admit", unit="cell", key=key,
                                   book=book, page=page, col=col, slot=slot),
                       payload), None)


def _confirm(db, cell, payload, **kw):
    pg, col, slot = cell
    return glyphdb_admit([_ev(f"{BOOK}:{pg}:{col}:{slot}", payload, pg, col, slot)],
                         db_path=str(db), **kw)


def test_shape_and_reading_land_in_different_columns(lib):
    """已/巳 这类：字形进字形索引，释读进 admissions.char。

    字形层的 near_form 护栏本来就是防「形状判据自己会认错」，字形库若被
    释读污染，将来一个真刻成这形状、该读别的字的实例会错误继承这次的释读。
    """
    db, cells = lib
    pg, col, slot = cells[0]
    r = _confirm(db, cells[0], {"v": "confirm", "shape": "巳", "reading": "已",
                                "conversion": 1})
    assert r.added == 1, r.errors

    iid = f"v2:{BOOK}:{pg}:{col}:{slot}"
    c = sqlite3.connect(db)
    label, _semantic = c.execute(
        "select label, semantic from instances where instance_id=?", (iid,)).fetchone()
    char, prov = c.execute(
        "select char, provenance from admissions where instance_id=?", (iid,)).fetchone()
    c.close()
    assert label == "巳", f"字形索引该存刻本的形，实际 {label}"
    # 读法取消（用户 2026-09-26）：admissions.char 也记字形，事件里旧的 reading 不再读
    assert char == "巳", f"admissions.char 该存字形，实际 {char}"
    assert prov == "human"


def test_v2_ids_do_not_overwrite_v1_records(lib):
    """v2 的 id 必须加前缀——v1 的 idx 与 v2 的 slot 差一格，撞车会改写旧记录。

    实测 vol01/24 c1：库里 `vol01:24:1:2` 是「每」，v2 的 `1:2` 是「書」，
    170 个同 id 命中里 0 个一致。

    这里先自己往库里插一条 v1 形态的记录（不带前缀）当对照——原先是去真库里
    翻一条，翻不到就 skip。
    """
    db, cells = lib
    pg, col, slot = cells[0]
    v1_id = f"{BOOK}:{pg}:{col}:{slot}"          # v1 命名空间：没有 v2: 前缀
    c = sqlite3.connect(db)
    c.execute("insert into admissions (instance_id, char, provenance, admitted_at) "
              "values (?,?,?,datetime('now'))", (v1_id, "每", "human"))
    c.commit()
    c.close()

    _confirm(db, cells[0], {"v": "confirm", "shape": "次", "reading": "次"})

    c = sqlite3.connect(db)
    after = c.execute("select char from admissions where instance_id=?",
                      (v1_id,)).fetchone()[0]
    v2 = c.execute("select char from admissions where instance_id=?",
                   (f"v2:{v1_id}",)).fetchone()
    c.close()
    assert after == "每", f"v1 记录被改写了：每 → {after}"
    assert v2 is not None and v2[0] == "次", "v2 记录没落到 v2: 命名空间"


def test_not_a_char_and_skip_do_not_enter_the_library(lib):
    db, cells = lib
    (p1, c1, s1), (p2, c2, s2) = cells[0], cells[1]
    r = glyphdb_admit([
        _ev(f"{BOOK}:{p1}:{c1}:{s1}", {"v": "not_a_char"}, p1, c1, s1),
        _ev(f"{BOOK}:{p2}:{c2}:{s2}", {"v": "skip"}, p2, c2, s2),
    ], db_path=str(db))
    assert r.added == 0 and r.skipped == 2


def test_no_glyph_lib_skips_admit_but_is_not_an_error(lib):
    """勾了「字形不入库」：正常裁决（不算 skipped/errors），但不落 GlyphDB。"""
    db, cells = lib
    c = sqlite3.connect(db)
    before = c.execute("select count(*) from admissions").fetchone()[0]
    c.close()

    r = _confirm(db, cells[0], {"v": "confirm", "shape": "次", "reading": "次",
                                "no_glyph_lib": True})
    c = sqlite3.connect(db)
    after = c.execute("select count(*) from admissions").fetchone()[0]
    c.close()
    assert before == after, "no_glyph_lib 的事件不该写进 GlyphDB"
    assert r.no_lib == 1
    assert r.added == 0 and r.skipped == 0 and not r.errors


def test_dry_run_writes_nothing(lib):
    db, cells = lib
    c = sqlite3.connect(db)
    before = c.execute("select count(*) from admissions").fetchone()[0]
    c.close()
    r = _confirm(db, cells[0], {"v": "confirm", "shape": "次"}, dry_run=True)
    c = sqlite3.connect(db)
    after = c.execute("select count(*) from admissions").fetchone()[0]
    c.close()
    assert r.added == 1 and before == after


def test_missing_patch_is_an_error_not_a_silent_skip(lib):
    """字块缓存里没有这一格时要报错，不能静默当成「进库成功」。

    静默的后果是审查闭环少收了一条却没人知道——人裁过的位在库里找不到，
    下一轮又被当成没裁过再出一次卡。
    """
    db, _cells = lib
    r = glyphdb_admit([_ev(f"{BOOK}:{PAGE}:99:99",
                           {"v": "confirm", "shape": "次", "reading": "次"},
                           PAGE, 99, 99)], db_path=str(db))
    assert r.added == 0
    assert r.errors, "字块找不到却既没进库也没报错"


def _seed_machine_copy(db, iid, char, source_pv=None):
    """往库里插一条机器准入的刻例（模拟播种），可指定来源的 pipeline_version。"""
    import cv2
    import numpy as np
    from open_guji_cv.clustering.glyph_db import GlyphDB
    g = GlyphDB(db)
    img = np.full((64, 64), 255, np.uint8)
    cv2.rectangle(img, (20, 10), (44, 54), 0, 4)
    g.admit_instance(iid, char, cv2.imencode(".png", img)[1].tobytes(),
                     provenance="align", evidence={"test": True})
    if source_pv:
        g.conn.execute("UPDATE sources SET pipeline_version=? WHERE source_id=?",
                       (source_pv, iid.split(":")[0]))
        g.conn.commit()
    g.close()


def test_human_verdict_evicts_machine_copy_of_same_cell(lib):
    """播种 `<book>:p:c:s` 与人裁 `v2:<book>:p:c:s` 是同一格：人裁到了撤机器那份，
    否则人改判后机器那份带着旧字继续当刻例（2026-09-25 北行实测 17 格两份并存）。"""
    db, cells = lib
    pg, col, slot = cells[1]
    machine = f"{BOOK}:{pg}:{col}:{slot}"
    _seed_machine_copy(db, machine, "甲")
    r = _confirm(db, cells[1], {"v": "confirm", "shape": "乙"})
    assert r.added == 1, r.errors
    c = sqlite3.connect(db)
    assert c.execute("select count(*) from exemplars where instance_id=?",
                     (machine,)).fetchone()[0] == 0, "机器副本该被撤掉"
    assert c.execute("select count(*) from glyphs where char='甲'").fetchone()[0] == 0
    c.close()


def test_v1_namespace_twin_is_not_evicted(lib):
    """v1 来源（idx 坐标）同名 id 指的是另一格，人裁不能顺手撤它。"""
    db, cells = lib
    pg, col, slot = cells[2]
    v1 = f"{BOOK}:{pg}:{col}:{slot}"
    _seed_machine_copy(db, v1, "甲", source_pv="v1")
    r = _confirm(db, cells[2], {"v": "confirm", "shape": "乙"})
    assert r.added == 1, r.errors
    c = sqlite3.connect(db)
    assert c.execute("select count(*) from exemplars where instance_id=?",
                     (v1,)).fetchone()[0] == 1, "v1 同名 id 是另一格，不该撤"
    c.close()


def test_mojibake_shape_is_repaired_or_rejected(lib):
    """UTF-8 被当 cp1252 解过的乱码（「å†…」＝内）还原后进库；还原不了的不进库。"""
    db, cells = lib
    r = _confirm(db, cells[3], {"v": "confirm", "shape": "å†…"})
    assert r.added == 1, r.errors
    pg, col, slot = cells[3]
    c = sqlite3.connect(db)
    assert c.execute("select label from instances where instance_id=?",
                     (f"v2:{BOOK}:{pg}:{col}:{slot}",)).fetchone()[0] == "内"
    c.close()
    r = _confirm(db, cells[4], {"v": "confirm", "shape": "abc"})
    assert r.added == 0 and "不是单个汉字" in r.errors[0]


def test_relabel_without_cache_uses_library_patch(lib, monkeypatch):
    """字块缓存被清之后改判：图块用库里那张，改判照样落库。"""
    db, cells = lib
    assert _confirm(db, cells[5], {"v": "confirm", "shape": "甲"}).added == 1
    from open_guji_cv.products.cache import ImageCache
    monkeypatch.setattr(ImageCache, "get", lambda self, *a, **k: None)
    r = _confirm(db, cells[5], {"v": "confirm", "shape": "乙"})
    assert r.added == 1, r.errors
    pg, col, slot = cells[5]
    c = sqlite3.connect(db)
    assert c.execute("select label from instances where instance_id=?",
                     (f"v2:{BOOK}:{pg}:{col}:{slot}",)).fetchone()[0] == "乙"
    c.close()
