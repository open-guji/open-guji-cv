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


def test_match_excludes_self():
    """字位自己在库里时必须摘掉再比——自证不是证据。

    2026-08-25 用户实锤 vol01:22:5:4：审查页显示「最近刻例 vol01:22:5:4
    cov 1.00」，刻例编号与被审字位是同一个。进库通道的设计前提是「文本 ×
    形状两路同源性为零」，自比把形状那一路变成「上次进库时定的字」，
    独立性归零；match_solo（库 cov≥0.99 单独放行）更会被自证直接喂饱。
    """
    import numpy as np
    from open_guji_cv.clustering.match import GlyphMatcher

    rng = np.random.default_rng(3)
    a = (rng.random((64, 64)) > 0.7).astype(np.uint8)
    b = (rng.random((64, 64)) > 0.7).astype(np.uint8)
    m = GlyphMatcher()
    m.add("bk:1:1:1", "甲", a)
    m.add("bk:1:1:2", "乙", b)

    # 不摘：拿自己比自己，必然命中自己
    assert m.match(a).matched_id == "bk:1:1:1"
    # 摘掉自身：结果里不能再出现自己
    r = m.match(a, exclude_id="bk:1:1:1")
    assert r.matched_id != "bk:1:1:1"
    assert all(c != "甲" for c, _ in (r.candidates or [])) or r.verdict != "same"
    # 库里只有自己一条时，摘完就没得比了
    solo = GlyphMatcher()
    solo.add("bk:1:1:1", "甲", a)
    assert solo.match(a, exclude_id="bk:1:1:1").verdict == "diff"
