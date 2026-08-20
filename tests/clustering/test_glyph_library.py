"""glyph_library.py 单测：入库/检索/持久化/异体字独立条目。"""

import random

from open_guji_cv.clustering.glyph_library import GlyphLibrary
from open_guji_cv.clustering.synth import degrade, synthetic_glyph


def test_add_query_roundtrip(tmp_path):
    lib = GlyphLibrary(tmp_path / "store", feature_backend="raw")
    rng = random.Random(1)
    g_tong = synthetic_glyph(random.Random(10))
    g_cha = synthetic_glyph(random.Random(20))
    lib.add("通", "通", g_tong, book="book1")
    lib.add("查", "查", g_cha, book="book1")

    # 磨损版查询应命中对应字且判 same
    worn = degrade(g_tong, rng, wear=0.3)
    hits = lib.query(worn, k=2)
    assert hits[0].char == "通"
    assert hits[0].verdict == "same"

    # 完全无关字形不应高分命中
    stranger = synthetic_glyph(random.Random(999))
    hits = lib.query(stranger, k=2)
    assert all(h.verdict != "same" for h in hits)


def test_variants_are_separate_entries(tmp_path):
    """爲/為 是独立条目，绝不合并；semantic 支持按正字检索。"""
    lib = GlyphLibrary(tmp_path / "store", feature_backend="raw")
    lib.add("爲", "爲", synthetic_glyph(random.Random(1)), book="b1")
    lib.add("為", "爲", synthetic_glyph(random.Random(2)), book="b2")
    assert len(lib) == 2
    entries = lib.variants_in_edition("爲")
    assert {e.char for e in entries} == {"爲", "為"}
    assert lib.variants_in_edition("爲", edition_tag="b1")[0].char == "爲"


def test_persistence(tmp_path):
    store = tmp_path / "store"
    lib = GlyphLibrary(store, feature_backend="raw")
    g = synthetic_glyph(random.Random(5))
    lib.add("通", "通", g, book="book1", n_confirmed=42)
    lib.save()

    lib2 = GlyphLibrary(store, feature_backend="raw")
    assert len(lib2) == 1
    assert lib2.entries[0].n_confirmed == 42
    hits = lib2.query(g, k=1)
    assert hits[0].char == "通"
    assert hits[0].verdict == "same"


def test_edition_hint_boost(tmp_path):
    lib = GlyphLibrary(tmp_path / "store", feature_backend="raw")
    g = synthetic_glyph(random.Random(7))
    lib.add("通", "通", g, book="b1", edition_tag="ed1")
    hits = lib.query(g, edition_hint="ed1", k=1)
    assert hits and hits[0].char == "通"
