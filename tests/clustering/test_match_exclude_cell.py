# -*- coding: utf-8 -*-
"""留一法按同一物理格摘：v1 重键后 vol01:/v2: 精确格号要求 =0，v1: 前缀
（idx 坐标、未经形状确认）保留 ±2（字形库 12 §六，2026-09-27 收紧）。"""

import numpy as np

from open_guji_cv.clustering.match import GlyphMatcher, _cell_parts


def _img(k):
    a = np.zeros((64, 64), np.uint8)
    a[10:54, 20 + k:26 + k] = 1
    a[30:34, 10:54] = 1
    return a


def test_cell_parts():
    assert _cell_parts("v2:bxgb:8:1:3") == ("bxgb", 8, 1, 3, True)
    assert _cell_parts("vol02:15:8:10b") == ("vol02", 15, 8, 10, True)
    assert _cell_parts("font:iming:04E4B") is None
    # v1: 前缀是 idx 坐标，按 idx+1 换算格号，标 exact=False
    assert _cell_parts("v1:vol01:5:7:6") == ("vol01", 5, 7, 7, False)


def test_exclude_same_cell_exact_for_precise_ids():
    """vol01:/v2:（重键后精确格号坐标）之间格号差必须 =0，不再 ±2 一并摘。"""
    m = GlyphMatcher(k=10)
    same = _img(0)
    for iid in ("v2:bk:3:4:5", "bk:3:4:5"):
        m.add(iid, "十", same)
    for iid in ("bk:3:4:4", "bk:3:4:6", "bk:3:4:7"):
        m.add(iid, "十", _img(1))       # 相邻格：现在是真证据，不摘
    rows = {m._ids[j] for j in m._same_cell_rows("bk:3:4:5")}
    assert rows == {"v2:bk:3:4:5", "bk:3:4:5"}
    r = m.match(same, exclude_id="bk:3:4:5")
    assert r.matched_id != "v2:bk:3:4:5" and r.matched_id != "bk:3:4:5"


def test_exclude_same_cell_v1_keeps_tolerance():
    """有一边是 v1:（idx 换算、未经形状确认）时保留 ±2 容差。"""
    m = GlyphMatcher(k=10)
    same = _img(0)
    m.add("bk:3:4:5", "十", same)
    m.add("v1:bk:3:4:3", "十", same)     # idx=3 → 格号 4，差 1，v1 兜底摘掉
    m.add("v1:bk:3:4:6", "十", same)     # idx=6 → 格号 7，差 2，仍在容差内
    m.add("v1:bk:3:4:7", "十", _img(1))  # idx=7 → 格号 8，差 3，超出容差，留着
    rows = {m._ids[j] for j in m._same_cell_rows("bk:3:4:5")}
    assert rows == {"bk:3:4:5", "v1:bk:3:4:3", "v1:bk:3:4:6"}
