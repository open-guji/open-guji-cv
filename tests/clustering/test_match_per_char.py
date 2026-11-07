"""kNN 每字限额（GlyphMatcher.per_char）：缺省不限与原排序一致；限额时同字不超过 per_char、按相似度取满 k。"""

import numpy as np

from open_guji_cv.clustering.match import GlyphMatcher


def _m(chars, k):
    m = GlyphMatcher(k=k)
    m._chars = list(chars)
    m._ids = [f"i{j}" for j in range(len(chars))]
    return m


def test_cap_limits_each_char_and_fills_k():
    m = _m("甲甲甲甲乙乙丙丁", k=4)
    m.per_char = 2
    sims = np.array([0.99, 0.98, 0.97, 0.96, 0.95, 0.94, 0.93, 0.92], dtype=np.float32)
    assert m._diverse_top(sims, set()) == [0, 1, 4, 5]
    m.per_char = 1
    assert m._diverse_top(sims, set()) == [0, 4, 6, 7]


def test_cap_skips_excluded_rows():
    m = _m("甲甲乙乙", k=3)
    m.per_char = 1
    sims = np.array([0.99, 0.98, 0.97, 0.96], dtype=np.float32)
    assert m._diverse_top(sims, {0}) == [1, 2]


def test_default_is_unlimited():
    assert GlyphMatcher(k=10).per_char == 0


def test_top_char_gets_its_own_cap():
    m = _m("甲甲甲甲乙乙乙丙", k=6)
    m.per_char, m.per_char_top = 1, 3
    sims = np.array([0.99, 0.98, 0.97, 0.96, 0.95, 0.94, 0.93, 0.92], dtype=np.float32)
    assert m._diverse_top(sims, set()) == [0, 1, 2, 4, 7]


def test_params_default_out_of_dump_and_applied():
    from open_guji_cv.steps.glyph_match import GlyphMatchParams, _with_knn_cap
    d = GlyphMatchParams(db_path="x.db", db_fingerprint="fp").model_dump()
    assert "knn_per_char" not in d and "knn_per_char_top" not in d
    d = GlyphMatchParams(db_path="x.db", db_fingerprint="fp", knn_per_char=2, knn_per_char_top=5).model_dump()
    assert d["knn_per_char"] == 2 and d["knn_per_char_top"] == 5
    base = GlyphMatcher(k=10)
    g = _with_knn_cap(base, 2, 5)
    assert (g.per_char, g.per_char_top) == (2, 5) and base.per_char == 0
