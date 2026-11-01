"""字形库 edition 一律是书 ID（2026-11-01 Sheldon 定）：没声明 book_edition 就拒写，体检报警。"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from open_guji_cv.clustering.glyph_db import GlyphDB, MissingBookEdition
from open_guji_cv.clustering.glyph_ledger import connect_ro, edition_problems


def _png() -> bytes:
    img = np.full((40, 40), 255, np.uint8)
    cv2.rectangle(img, (8, 8), (30, 30), 0, 2)
    return cv2.imencode(".png", img)[1].tobytes()


@pytest.fixture
def strict(monkeypatch):
    monkeypatch.setattr(GlyphDB, "require_book_edition", True)


def test_admit_refuses_without_book_edition(tmp_path, strict):
    db = GlyphDB(tmp_path / "g.db")
    with pytest.raises(MissingBookEdition):
        db.admit_instance("v2:1:1:1", "字", _png(), provenance="t")
    assert db.conn.execute("SELECT COUNT(*) FROM admissions").fetchone()[0] == 0
    db.set_book_edition("bookid123")
    assert db.admit_instance("v2:1:1:1", "字", _png(), provenance="t") is True
    assert db.conn.execute("SELECT edition_tag FROM glyphs").fetchone()[0] == "bookid123"


def test_explicit_edition_tag_still_allowed(tmp_path, strict):
    db = GlyphDB(tmp_path / "g.db")
    assert db.admit_instance("v2:1:1:1", "字", _png(), provenance="t", edition_tag="bookid123")


def test_edition_problems(tmp_path, strict):
    p = tmp_path / "g.db"
    db = GlyphDB(p)
    db.admit_instance("v2:1:1:1", "字", _png(), provenance="t", edition_tag="v2")
    db.close()
    c = connect_ro(p)
    probs = edition_problems(c)
    c.close()
    assert any("book_edition 缺失" in x for x in probs)
    assert any("'v2'" in x for x in probs)
    db = GlyphDB(p)
    db.set_book_edition("bookid123")
    db.close()
    c = connect_ro(p)
    assert edition_problems(c) == []
    c.close()
