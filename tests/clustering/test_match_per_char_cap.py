"""`GlyphMatcher` 近邻按字封顶（`per_char_cap`，2026-11-03 全唐文 r6：請 34 例把 諸 3 例挤出前 10 近邻）。"""

import numpy as np

from open_guji_cv.clustering.match import GlyphMatcher


def _m(chars):
    m = GlyphMatcher(k=4)
    m._ids = [f"x:{i}" for i in range(len(chars))]
    m._chars = list(chars)
    return m


def test_cap_zero_keeps_plain_topk():
    m = _m("AAAAAB")
    sims = np.array([0.99, 0.98, 0.97, 0.96, 0.95, 0.90], dtype=np.float32)
    # 不封顶时前 4 名全是 A，B 进不来（这就是被挤掉的情形）
    assert [m._chars[j] for j in np.argsort(-sims)[: m.k]] == list("AAAA")


def test_cap_lets_minority_char_in_and_fills_k():
    m = _m("AAAAABC")
    sims = np.array([0.99, 0.98, 0.97, 0.96, 0.95, 0.90, 0.80], dtype=np.float32)
    top = m._top_per_char(sims, set(), cap=2)
    assert [m._chars[j] for j in top] == list("AABC")
    assert top == [0, 1, 5, 6]


def test_cap_skips_excluded_rows():
    m = _m("AABB")
    sims = np.array([0.99, 0.98, 0.97, 0.96], dtype=np.float32)
    sims[0] = -np.inf
    assert m._top_per_char(sims, {0}, cap=1) == [1, 2]


def test_cap_widens_window_when_needed():
    # 前 64 名全是同一个字，第二个字排在 200 名开外：窗口要放大才取得到
    chars = "A" * 300 + "B"
    m = _m(chars)
    sims = np.linspace(1.0, 0.5, len(chars)).astype(np.float32)
    top = m._top_per_char(sims, set(), cap=1)
    assert [m._chars[j] for j in top] == ["A", "B"]


def test_supplement_rows_adds_missing_chars_only():
    m = _m("AAAAABBC")
    sims = np.array([0.99, 0.98, 0.97, 0.96, 0.95, 0.90, 0.89, 0.80], dtype=np.float32)
    top = [0, 1, 2, 3]
    assert m._supplement_rows(sims, set(), top, n=1, window=50) == [5, 7]
    assert m._supplement_rows(sims, set(), top, n=2, window=50) == [5, 6, 7]
    assert m._supplement_rows(sims, set(), top, n=1, window=6) == [5]
