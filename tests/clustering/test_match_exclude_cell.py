# -*- coding: utf-8 -*-
"""留一法按同一物理格摘：v2:/播种/v1（格号−1）/漂移邻格都摘，远处同列的不摘。"""

import numpy as np

from open_guji_cv.clustering.match import GlyphMatcher, _cell_parts


def _img(k):
    a = np.zeros((64, 64), np.uint8)
    a[10:54, 20 + k:26 + k] = 1
    a[30:34, 10:54] = 1
    return a


def test_cell_parts():
    assert _cell_parts("v2:bxgb:8:1:3") == ("bxgb", 8, 1, 3)
    assert _cell_parts("vol02:15:8:10b") == ("vol02", 15, 8, 10)
    assert _cell_parts("font:iming:04E4B") is None


def test_exclude_same_cell_across_namespaces():
    m = GlyphMatcher(k=10)
    same = _img(0)
    for iid in ("v2:bk:3:4:5", "bk:3:4:5", "bk:3:4:4", "bk:3:4:7"):
        m.add(iid, "十", same)
    m.add("bk:3:4:12", "十", _img(1))           # 同列远处：真证据，留着
    rows = {m._ids[j] for j in m._same_cell_rows("bk:3:4:5")}
    assert rows == {"v2:bk:3:4:5", "bk:3:4:5", "bk:3:4:4", "bk:3:4:7"}
    r = m.match(same, exclude_id="bk:3:4:5")
    assert r.matched_id in (None, "bk:3:4:12")
