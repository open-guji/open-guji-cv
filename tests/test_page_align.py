# -*- coding: utf-8 -*-
"""`utils/page_align.py`：刻本页 ↔ 逐列本半叶的自动配页（Step3 `page_map`）。数据全是自造的。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.utils import page_align as PA

NCOL = 9
CELLS = PA.N_EXTRA + PA.N_SLOTS


def _half(rng, kind="text"):
    """随机一个半叶的占格：每列从第 1 格起写到随机长度，偶尔抬头一格。"""
    o = np.zeros((NCOL, CELLS), dtype=bool)
    if kind == "empty":
        return o
    for c in range(NCOL):
        n = int(rng.integers(0, PA.N_SLOTS + 1)) if rng.random() < 0.5 else PA.N_SLOTS - 2
        start = PA.N_EXTRA + (0 if rng.random() < 0.3 else 1)
        o[c, start:start + n] = True
        if rng.random() < 0.08:
            o[c, PA.N_EXTRA - 1] = True
    return o


def _book(seed=0, m=120, covers=(0, 1, 60, 61)):
    rng = np.random.default_rng(seed)
    O = np.stack([_half(rng, "empty" if i in covers else "text") for i in range(m)])
    empty = ~O.reshape(m, -1).any(axis=1)
    cover = np.zeros(m, dtype=bool)
    cover[list(covers)] = True
    return O, empty, cover


def _noisy(o, rng, flip=0.03):
    g = o.copy()
    mask = rng.random(g.shape) < flip
    g[mask] = ~g[mask]
    return g


def _run(seq, O, empty, cover, seed=1, pins=None, raw_dup=None):
    """`seq` 是每页对应的半叶号（None ＝ 封面之类不在逐列本里的页，给一张满墨图）。"""
    rng = np.random.default_rng(seed)
    pages = list(range(1, len(seq) + 1))
    grids, raws, inks = [], [], []
    for h in seq:
        if h is None:
            g = np.zeros((NCOL, CELLS), dtype=bool)   # 书脊标签、护叶：框里没字
        else:
            g = _noisy(O[h], rng)
        grids.append(g)
        raws.append(g.astype(np.float32) * 0.2)
        inks.append(0.1)
    if raw_dup:
        for k in raw_dup:
            raws[k] = raws[k - 1].copy()
            grids[k] = grids[k - 1].copy()
    return PA.align(pages, grids, inks, O, empty, cover, pins=pins, raw=raws)


def _halves(res):
    return [res.matches[p].half for p in sorted(res.matches)]


def test_finds_start_anywhere_in_book():
    O, empty, cover = _book()
    seq = list(range(30, 58))
    res = _run(seq, O, empty, cover)
    assert _halves(res) == seq
    assert all(m.confident for m in res.matches.values())


def test_skips_cover_page_and_blank_cover_halves():
    O, empty, cover = _book()
    seq = [None] + list(range(50, 60)) + list(range(62, 70))   # 书脊标签页；60/61 是卷端牌记空半叶
    res = _run(seq, O, empty, cover)
    got = _halves(res)
    assert got[0] is None
    assert got[1:] == seq[1:]


def test_missing_scan_skips_half():
    O, empty, cover = _book()
    seq = list(range(20, 35)) + list(range(36, 50))            # 缺扫半叶 35
    res = _run(seq, O, empty, cover)
    assert _halves(res) == seq


def test_duplicate_scan_is_dropped():
    O, empty, cover = _book()
    seq = list(range(20, 30)) + [29] + list(range(30, 40))     # 第 11 页是第 10 页的重扫
    res = _run(seq, O, empty, cover, raw_dup=[10])
    got = _halves(res)
    assert got[10] is None and res.matches[11].how == "dup"
    assert got[:10] == seq[:10] and got[11:] == seq[11:]
    assert res.dups == [11]


def test_swapped_half_order():
    O, empty, cover = _book()
    seq = list(range(20, 30)) + [31, 30] + list(range(32, 40))  # 前后半叶顺序反
    res = _run(seq, O, empty, cover)
    assert _halves(res) == seq


def test_pin_forces_page():
    O, empty, cover = _book()
    seq = list(range(20, 40))
    res = _run(seq, O, empty, cover, pins={5: 24, 6: None})
    got = _halves(res)
    assert got[4] == 24 and res.matches[5].how == "pin"
    assert got[5] is None


def test_gap_fill_takes_lone_unmatched_page():
    O, empty, cover = _book()
    seq = list(range(20, 40))
    rng = np.random.default_rng(3)
    pages = list(range(1, 21))
    grids = [_noisy(O[h], rng) for h in seq]
    grids[9] = ~O[29]                                          # 这一页图上异样（大印、整页抬头）
    res = PA.align(pages, grids, [0.1] * 20, O, empty, cover)
    assert res.matches[10].half == 29
    assert res.matches[10].how == "gap"
    assert not res.matches[10].confident


def test_slot_ink_reads_cells_between_lines():
    gray = np.full((230, 100), 255, dtype=np.uint8)
    # 一列 x 10–90，版框 y 10–220：格高 10；第 1、2 格涂黑，出格 -1 格也涂黑
    gray[11:29, 20:80] = 0
    gray[1:9, 20:80] = 0
    g = PA.slot_ink(gray, [(10, 90, 10, 220)])
    b = PA.binarize(g)
    assert b.shape == (1, CELLS)
    assert b[0, PA.N_EXTRA] and b[0, PA.N_EXTRA + 1] and not b[0, PA.N_EXTRA + 2]
    assert b[0, PA.N_EXTRA - 1]


def test_occupancy_maps_slots_and_raised():
    o = PA.occupancy([(0, {"slots": [-1, 1, 2, 21]}), (8, {"slots": [3]})])
    assert o[0, PA.N_EXTRA - 1] and o[0, PA.N_EXTRA] and o[0, PA.N_EXTRA + 20]
    assert o[8, PA.N_EXTRA + 2]
    assert o.sum() == 5


def test_row_segment_page_map_off_keeps_params_dump():
    """缺省 off：参数 dump 里没有 page_map 两项（老册指纹逐位不变）；开着时不再用离线表。"""
    from open_guji_cv.steps.row_segment import RowSegmentParams
    off = RowSegmentParams().model_dump()
    assert "page_map" not in off and "page_map_fingerprint" not in off
    on = RowSegmentParams(page_map="strict", page_map_fingerprint="abc")
    d = on.model_dump()
    assert d["page_map"] == "strict" and d["page_map_fingerprint"] == "abc"
    assert on.layout_prior == "" and "layout_prior" not in d


def test_page_columns_converts_canonical_x():
    """列窗口是规范空间（右上原点、x 向左），量墨要换成图像坐标；列从右到左排。"""
    from types import SimpleNamespace as C

    from open_guji_cv.products.kinds.borders import VLineRec
    from open_guji_cv.steps.row_segment_pagemap import _page_columns

    def col(n, left, right):
        return C(col=n, left_line=VLineRec(x_at_top=left, slope=0.0), right_line=VLineRec(x_at_top=right, slope=0.0),
                 border_top_y=10.0, border_bottom_y=220.0)
    win = C(columns=[col(2, 400.0, 200.0), col(1, 200.0, 10.0)])
    assert _page_columns(win, 1000) == [(800.0, 990.0, 10.0, 220.0), (600.0, 800.0, 10.0, 220.0)]


def test_scrambled_scan_order_within_few_leaves():
    """vol11 那种：几叶之内次序颠倒（不只是相邻对调）、中间还缺扫几个半叶，整册起点也要找对。
    次序照抄 vol11 前 40 页的实配（半叶号减 1518）。"""
    O, empty, cover = _book(m=400, covers=(0, 1))
    seq = [200, 203, 205, 204, 207, 206, 210, 208, 211, 215, 214, 212, 216, 217, 221, 219, 218, 222,
           220, 223, 227, 225, 224, 228, 226, 229, 233, 230, 234, 232, 235, 237, 238, 241, 240, 243,
           242, 245, 244, 247]
    res = _run(seq, O, empty, cover)
    assert _halves(res) == seq


def test_reorder_keeps_tied_pages_in_place():
    """次序正常、满页彼此打平时，局部重排不挪页。"""
    O, empty, cover = _book()
    O[30:40] = O[30]                                           # 十个一模一样的满页
    seq = list(range(25, 45))
    res = _run(seq, O, empty, cover)
    assert _halves(res) == seq
    assert all(m.how == "pair" for m in res.matches.values())
