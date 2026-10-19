# -*- coding: utf-8 -*-
"""Step5-a 借来的刻例降一档、借库进指纹（共享方案 S6）。

自造字形库与桩匹配器，不碰真书数据。
"""
from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass

import cv2
import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.clustering.match import MatchResult
from open_guji_cv.core.engine import params_hash
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps import glyph_match as gm
from open_guji_cv.steps.glyph_match import GlyphMatchParams, demote_borrowed

SOFT = STEPS["glyph_match"].spec.soft_params


def _same(iid, hits=()):
    return MatchResult("same", "甲", iid, 0.998, 3.0, [("甲", 0.998), ("乙", 0.9)], n_verified=3,
                       same_hits=tuple(hits) or ((iid, 0.998, 3.0),))


def test_borrow_name_strips_machine_paths():
    assert gm._borrow_name("/h/main/.borrowed/glyphlib-qkp-v1/output/glyph_store") == "glyphlib-qkp-v1"
    assert gm._borrow_name(r"D:\ws\lib-ws\output\glyph_store") == "lib-ws"
    assert gm._borrow_name("/x/some_store") == "some_store"


def test_demote_borrowed_only_when_no_local_same():
    lent = frozenset({"lib:a", "lib:b"})
    # 只有借来的判 same → unsure，字不定，记来源
    assert demote_borrowed(_same("lib:a", [("lib:a", 0.998, 3.0), ("lib:b", 0.997, 4.0)]), lent) == \
        ("unsure", None, None, 0.998, 3.0, "lib:a")
    # 本书也有条目判 same → 本书优先，证据换成本书那条
    assert demote_borrowed(_same("lib:a", [("lib:a", 0.998, 3.0), ("vol01:1:2:3", 0.997, 5.0)]), lent) == \
        ("same", "甲", "vol01:1:2:3", 0.997, 5.0, None)
    # 命中本书、没借库、不是 same：原样
    assert demote_borrowed(_same("vol01:1:2:3"), lent)[5] is None
    assert demote_borrowed(_same("lib:a"), frozenset())[:3] == ("same", "甲", "lib:a")
    unsure = MatchResult("unsure", None, None, 0.99, 8.0, [("甲", 0.99)])
    assert demote_borrowed(unsure, lent)[0] == "unsure"


def _db_with_borrowed(path, stores):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE borrowed (instance_id TEXT PRIMARY KEY, store TEXT)")
    c.executemany("INSERT INTO borrowed VALUES (?,?)", [(f"i{n}", s) for n, s in enumerate(stores)])
    c.commit()
    c.close()


def test_no_borrow_keeps_params_hash(tmp_path):
    """没借库：borrow_fingerprint 是空串、不进 dump，参数哈希与 S6 之前逐位相同；借了才进、换库就变。"""
    plain = GlyphMatchParams(db_path=str(tmp_path / "none.db"), db_fingerprint="aaaa")
    assert plain.borrow_fingerprint == "" and "borrow_fingerprint" not in plain.model_dump(mode="json")
    old = params_hash(plain, SOFT)

    db1 = tmp_path / "b1.db"
    _db_with_borrowed(db1, ["/h/.borrowed/glyphlib-qkp-v1/output/glyph_store"] * 2
                      + ["/w/lib-ws/output/glyph_store"])
    p1 = GlyphMatchParams(db_path=str(db1), db_fingerprint="aaaa")
    assert p1.borrow_fingerprint == "glyphlib-qkp-v1,lib-ws"
    assert gm.borrowed_ids(db1) == {"i0", "i1", "i2"}
    db2 = tmp_path / "b2.db"
    _db_with_borrowed(db2, ["/h/.borrowed/glyphlib-qkp-v2/output/glyph_store"])
    p2 = GlyphMatchParams(db_path=str(db2), db_fingerprint="aaaa")
    assert len({old, params_hash(p1, SOFT), params_hash(p2, SOFT)}) == 3

    nob = tmp_path / "nob.db"                 # 旧库没有 borrowed 表：当没借
    sqlite3.connect(nob).close()
    assert gm.borrow_fingerprint(nob) == "" and gm.borrowed_ids(nob) == frozenset()


@pytest.mark.parametrize("hits,want", [
    ((("lib:1", 0.998, 3.0),), ("unsure", None, None, "borrowed:lib:1")),
    ((("lib:1", 0.998, 3.0), ("v2:loc:1:1:1", 0.997, 4.0)), ("same", "甲", "v2:loc:1:1:1", None)),
])
def test_step_demotes_borrowed_same(tmp_path, monkeypatch, ws, fixture_page, hits, want):
    """run_page：只有借来的命中 → unsure、不走共识升档；本书也命中 → same、证据是本书条目。"""
    from helpers import run_keben_from_raw

    from open_guji_cv.core.book import load_book

    @dataclass
    class _Stub:
        def match(self, img, exclude_id=None):
            return MatchResult("same", "甲", hits[0][0], 0.998, 3.0, [("甲", 0.998)], n_verified=1,
                               same_hits=hits)

    ctx, _ = run_keben_from_raw(tmp_path, monkeypatch, book=load_book("keben"), gray=fixture_page)
    step = STEPS["glyph_match"]
    monkeypatch.setattr(type(step), "_matcher", lambda self, p: _Stub())
    monkeypatch.setattr(gm, "borrowed_ids", lambda _p: frozenset({"lib:1"}))
    monkeypatch.setattr(gm, "human_confirmed_counts", lambda _p: {"甲": 50})   # 共识升档的条件都满足
    ctx.params["glyph_match"] = GlyphMatchParams(db_fingerprint="fp", borrow_fingerprint="glyphlib-tst-v1")
    recs = [r for cc in step.run_page(ctx, 1)["glyph_match"].columns for r in cc.chars]
    assert recs
    assert {(r.verdict, r.char, r.matched_id, r.via) for r in recs} == {want}


def _png(seed: int):
    from open_guji_cv.clustering.synth import degrade, synthetic_glyph
    g = degrade(synthetic_glyph(random.Random(100 + seed)), random.Random(seed), wear=0.3)
    ok, buf = cv2.imencode(".png", 255 - (g * 255).astype("uint8"))
    assert ok
    return buf.tobytes()


def test_real_db_borrowed_hit_is_demoted(tmp_path):
    """真库：借来的刻例装进 glyph.db，查它自己的图 → 匹配器判 same，降一档后是 unsure。"""
    from open_guji_cv.clustering.glyph_db import (
        GlyphDB,
        export_store,
        rebuild_from_store,
    )
    from open_guji_cv.clustering.seeding import load_matcher_from_db

    def store(name, rows):
        db = GlyphDB(tmp_path / f"{name}.sqlite")
        try:
            for iid, ch, seed in rows:
                assert db.admit_instance(iid, ch, _png(seed), provenance="human", edition_tag=name,
                                         page="1", col=seed, idx=1)
            export_store(db, tmp_path / name / "output" / "glyph_store")
        finally:
            db.close()
        return tmp_path / name / "output" / "glyph_store"

    own = store("ownbook", [("vol01:1:1:1", "甲", 1)])
    lib = store("glyphlib-tst-v1", [("srcbook:vol01:1:2:1", "乙", 2)])
    dbp = tmp_path / "glyph.db"
    rebuild_from_store(own, dbp, extra_stores=[lib])
    assert gm.borrow_fingerprint(dbp) == "glyphlib-tst-v1"
    lent = gm.borrowed_ids(dbp)
    assert lent == {"srcbook:vol01:1:2:1"}

    db = GlyphDB(dbp)
    try:
        matcher, _ = load_matcher_from_db(db)
        img = db.conn.execute("SELECT patch_png FROM instances WHERE instance_id = ?",
                              ("srcbook:vol01:1:2:1",)).fetchone()[0]
    finally:
        db.close()
    from open_guji_cv.clustering.normalize import normalize_patch
    m = matcher.match(normalize_patch(cv2.imdecode(__import__("numpy").frombuffer(img, "uint8"), 0)))
    assert m.verdict == "same" and m.matched_id == "srcbook:vol01:1:2:1"
    assert demote_borrowed(m, lent)[0] == "unsure"
