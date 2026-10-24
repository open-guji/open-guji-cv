"""`ops/glyph_diff.py`：换字形库后只点名邻居、命中条目、共识门槛变了的格。数据全在本测试里现造。"""

import numpy as np

from open_guji_cv.clustering.match import GlyphMatcher
from open_guji_cv.ops.glyph_diff import LibView, cell_reasons, page_neighbours
from open_guji_cv.products.kinds.recog import MatchRec
from open_guji_cv.steps.glyph_match import GlyphMatchParams


def _blob(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    a = np.zeros((64, 64), np.uint8)
    for _ in range(6):
        y, x = rng.integers(4, 52, size=2)
        h, w = rng.integers(3, 12, size=2)
        a[y:y + h, x:x + w] = 255
    return a


def _view(entries, confirmed=None) -> LibView:
    m = GlyphMatcher(k=3)
    for iid, ch, img in entries:
        m.add(iid, ch, img)
    v = LibView(full=m, sub=None, confirmed=confirmed or {}, borrowed=frozenset())
    v.live = {}
    for iid, ch, _ in entries:
        v.live.setdefault(iid, set()).add(ch)
    return v


def _params(**kw) -> GlyphMatchParams:
    return GlyphMatchParams(db_path="unused.db", db_fingerprint="x", borrow_fingerprint="-", font_tier=False, **kw)


BASE = [(f"v2:vol01:1:1:{i}", "甲乙丙丁戊己庚辛"[i], _blob(i)) for i in range(8)]


def test_far_exemplar_keeps_neighbours_close_one_changes_them():
    queries = [_blob(0), _blob(100)]
    ids = ["vol02:1:1:1", "vol02:1:1:2"]
    old = _view(BASE)
    nb_old = page_neighbours(old, queries, ids, exclude_self=True)
    # 一条与查询毫不相干的新刻例（全空白）挤不进任何一格的前 3
    far = _view(BASE + [("v2:vol03:1:1:1", "壬", np.zeros((64, 64), np.uint8))])
    assert page_neighbours(far, queries, ids, exclude_self=True)[0] == nb_old[0]
    # 和第 2 个查询一模一样的新刻例：它的邻居变了，第 1 格不变
    near = _view(BASE + [("v2:vol03:1:1:2", "癸", _blob(100))])
    nb_near = page_neighbours(near, queries, ids, exclude_self=True)
    assert nb_near[0] == nb_old[0]
    assert nb_near[1] != nb_old[1]


def test_self_row_is_excluded_like_5a():
    """新库里进了这一格自己（人裁），5a 会把它摘掉，邻居不算变。"""
    queries = [_blob(100)]
    old = _view(BASE)
    new = _view(BASE + [("v2:vol02:1:1:1", "癸", _blob(100))])
    assert (page_neighbours(new, queries, ["vol02:1:1:1"], exclude_self=True)
            == page_neighbours(old, queries, ["vol02:1:1:1"], exclude_self=True))


def test_relabel_and_patch_change_count_as_neighbour_change():
    queries = [_blob(3)]
    old = _view(BASE)
    relabel = _view([(i, "丁" if c != "丁" else "子", im) for i, c, im in BASE])
    assert page_neighbours(relabel, queries, ["q"], True) != page_neighbours(old, queries, ["q"], True)


def test_cell_reasons_dead_and_consensus():
    p = _params()
    old = _view(BASE, confirmed={"甲": 2})
    new = _view(BASE[1:], confirmed={"甲": 3})
    same = [((("a", "甲", b"x"),),)]
    r = MatchRec(id="vol02:1:1:1", slot=1, verdict="same", char="甲", matched_id=BASE[0][0],
                 candidates=[("甲", 0.999)])
    assert cell_reasons(r, same, same, old, new, p) == ["dead", "consensus"]
    r2 = MatchRec(id="vol02:1:1:2", slot=2, verdict="unsure", candidates=[("乙", 0.95)])
    assert cell_reasons(r2, same, same, old, new, p) == []
    assert cell_reasons(r2, same, [((),)], old, new, p) == ["knn"]
    t = MatchRec(id="vol02:1:1:3", slot=3, verdict="diff", guard="timeout")
    assert cell_reasons(t, same, same, old, new, p) == ["timeout"]


def test_consensus_count_recorded_in_via():
    """共识升档的格 `via` 记着例数：没跨门槛、例数变了也要重算，否则复用的记录与重算的不逐字节相同。"""
    p = _params()
    old = _view(BASE, confirmed={"乙": 15})
    new = _view(BASE, confirmed={"乙": 16})
    nb = [((),)]
    r = MatchRec(id="vol02:1:1:4", slot=4, verdict="same", char="乙", via="consensus:15",
                 candidates=[("乙", 0.995)])
    assert cell_reasons(r, nb, nb, old, new, p) == ["consensus"]
    plain = MatchRec(id="vol02:1:1:5", slot=5, verdict="unsure", candidates=[("乙", 0.95)])
    assert cell_reasons(plain, nb, nb, old, new, p) == []
