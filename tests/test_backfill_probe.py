"""clustering.backfill_probe：回库前核验（待回库例撞形近常用字、回库模拟抢首位）。数据全是现造的图块。"""
import numpy as np

from open_guji_cv.clustering.backfill_probe import BackfillProbe
from open_guji_cv.clustering.match import GlyphMatcher


def _cross(dx=0, dy=0, w=4):
    p = np.zeros((64, 64), dtype=np.uint8)
    p[10 + dy:54 + dy, 30 + dx:30 + dx + w] = 1
    p[30 + dy:30 + dy + w, 10 + dx:54 + dx] = 1
    return p


def _box():
    p = np.zeros((64, 64), dtype=np.uint8)
    p[12:52, 12:16] = p[12:52, 48:52] = p[12:16, 12:52] = p[48:52, 12:52] = 1
    return p


def _lib():
    m = GlyphMatcher(k=10)
    for i, (dx, dy) in enumerate([(2, 0), (0, 2), (2, 2), (-2, 0)]):
        m.add(f"v2:01:1:1:{i + 1}", "十", _cross(dx, dy))
    for i in range(3):
        m.add(f"v2:01:2:1:{i + 1}", "口", _box())
    return m


def test_probe_one_flags_common_rival():
    p = BackfillProbe("", matcher=_lib(), knn_k=10)
    row = p.probe_one("01:9:9:9", "𠂇", _cross(1, 1), common_min=3, cov_min=0.0)
    assert row.first == "十" and row.self_cov is None
    assert row.flag and row.flag_chars == ["十"] and row.n_rival == 4 and row.n_self == 0
    d = row.to_dict()
    assert d["top"][0][0] == "十"


def test_steal_check_harm_and_skip():
    p = BackfillProbe("", matcher=_lib(), knn_k=10)
    cells = [("01:5:1:1", "十", _cross()), ("01:5:1:2", "口", _box())]
    r = p.steal_check([("01:9:9:9", "𠂇", _cross())], cells)
    assert r["harm"] == {"𠂇": ["01:5:1:1"]}
    assert r["help"] == {} and r["cells"] == 2
    # 库本身没被改
    assert "𠂇" not in p.matcher._char_set and len(p.matcher) == 7


def test_steal_check_help():
    p = BackfillProbe("", matcher=_lib(), knn_k=10)
    r = p.steal_check([("01:9:9:8", "大", _cross(0, 0, w=6))], [("01:5:1:3", "大", _cross(0, 0, w=6))])
    assert r["help"] == {"大": ["01:5:1:3"]} and r["harm"] == {}


def test_exclude_ids():
    p = BackfillProbe("", matcher=_lib(), knn_k=10, exclude_ids={"v2:01:2:1:1"})
    assert p.n_lib == {"十": 4, "口": 2}
