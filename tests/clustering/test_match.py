"""GlyphMatcher 单测：三档判决、两道护栏、证据完整性。

合成字形沿用 test_verify_cov 的构造；护栏用真实家族字（諭/論 在
NEVER_MATCH_FAMILIES 里）配合合成图形验证逻辑，不依赖真实刻例。
"""

import random

import numpy as np

from open_guji_cv.clustering.match import (NEVER_MATCH_FAMILIES,
                                           GlyphMatcher)
from open_guji_cv.clustering.synth import synthetic_glyph


def _pad(g, size=64):
    out = np.zeros((size, size), dtype=np.uint8)
    h, w = g.shape
    y, x = (size - h) // 2, (size - w) // 2
    out[y:y + h, x:x + w] = g
    return out


def _glyph(seed=1):
    return _pad(synthetic_glyph(random.Random(seed)))


def test_empty_db_is_diff():
    m = GlyphMatcher()
    r = m.match(_glyph(1))
    assert r.verdict == "diff" and r.char is None and r.n_verified == 0


def test_perfect_match_inherits_char():
    m = GlyphMatcher()
    m.add("db:1", "文", _glyph(1))
    m.add("db:2", "山", _glyph(2))
    r = m.match(_glyph(1))
    assert r.verdict == "same"
    assert r.char == "文" and r.matched_id == "db:1"
    assert r.cov >= 0.992 and r.n_verified >= 1


def test_unrelated_glyph_is_diff_or_unsure_never_same():
    m = GlyphMatcher()
    for i in range(2, 8):
        m.add(f"db:{i}", f"字{i}", _glyph(i))
    r = m.match(_glyph(1))
    assert r.verdict in ("diff", "unsure")
    assert r.char is None


def test_never_match_family_demotes_to_unsure():
    """same 命中的字若其形近对家也在库里 → 降档 unsure，两字都进候选。"""
    a, b = NEVER_MATCH_FAMILIES[0]          # 諭/論
    m = GlyphMatcher()
    m.add("db:a", a, _glyph(1))
    m.add("db:b", b, _glyph(9))             # 对家在库（图形无关，只看字表）
    r = m.match(_glyph(1))                  # 与 db:a 完美匹配
    assert r.verdict == "unsure" and r.guard == "never_match"
    assert r.char is None
    cands = dict(r.candidates)
    assert a in cands and b in cands
    assert cands[a] >= 0.992                # 命中方带真实 cov 先验


def test_never_match_partner_absent_no_demotion():
    a, _b = NEVER_MATCH_FAMILIES[0]
    m = GlyphMatcher()
    m.add("db:a", a, _glyph(1))
    m.add("db:x", "山", _glyph(2))
    r = m.match(_glyph(1))
    assert r.verdict == "same" and r.char == a and r.guard is None


def test_conflicting_same_hits_demote_to_unsure():
    """同一查询对两个不同字都判 same（库内不自洽）→ 降档 unsure。"""
    m = GlyphMatcher()
    g = _glyph(1)
    m.add("db:1", "甲", g)
    m.add("db:2", "乙", g)                  # 同图不同字：人为制造不自洽
    r = m.match(g)
    assert r.verdict == "unsure" and r.guard == "conflict"
    cands = dict(r.candidates)
    assert "甲" in cands and "乙" in cands


def test_evidence_serializes():
    m = GlyphMatcher()
    m.add("db:1", "文", _glyph(1))
    d = m.match(_glyph(1)).to_dict()
    assert d["verdict"] == "same" and d["matched_id"] == "db:1"
    assert isinstance(d["candidates"], list) and d["n_verified"] >= 1
