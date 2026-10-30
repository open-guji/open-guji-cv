# -*- coding: utf-8 -*-
"""列距救援（Step1 后处理，`books/siku_zongmu/pitch_rescue`）：列网里多挑一条假竖线、外侧整列落到网外时按列距重定。

纯内存构造：竖线位置取殿本 vol14 p186、vol20 p68 的真页形态（数是形态，不是 fixture 文件）。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.seg.frame_types import BorderDetectionResult, HLine, VLine
from open_guji_cv.books.siku_zongmu.column_pair_merge import line_xs
from open_guji_cv.books.siku_zongmu import pitch_rescue as pr

W, H = 2325, 3000
#: vol14 p186：c3 被劈成 83＋100，最右（规范空间 x 小）那列「春秋四傳三十八卷」落在网外
P186 = [524, 705, 886, 969, 1069, 1250, 1434, 1617, 1796, 1983]
GOOD = [343, 524, 705, 886, 1069, 1250, 1434, 1617, 1796, 1983]


def _res(xs):
    return BorderDetectionResult(width=W, height=H, top=HLine(300.0, 0.0, "top"),
                                 bottom=HLine(2700.0, 0.0, "bottom"),
                                 verticals=[VLine(float(x), 0.0) for x in xs])


def _gray(ink_cols):
    """规范空间 [x0, x1) 的列里铺墨（原图 x = W−1−x）。"""
    g = np.full((H, W), 255, np.uint8)
    for x0, x1 in ink_cols:
        g[400:2600:40, W - 1 - x1 + 30:W - 1 - x0 - 30] = 0
        g[400:2600, W - 1 - x1 + 60:W - 1 - x0 - 60:7] = 0
    return g


def test_normal_page_not_triggered():
    assert not pr.needs_rescue(GOOD)
    res = _res(GOOD)
    out, how = pr.rescue(res, _gray([]), lambda pitch: (_ for _ in ()).throw(AssertionError("不该重探")))
    assert how is None and out is res


def test_drop_and_extend_on_ink_side():
    g = _gray([(343, 524)])                       # 网外那列有字
    res = _res(P186)
    bad_grid = _res(P186)                         # 网格模式选不出版框对：原样
    out, how = pr.rescue(res, g, lambda pitch: bad_grid)
    assert how == "extend"
    assert [round(x) for x in line_xs(out)] == GOOD
    assert out.vline_filled[0] is True and not any(out.vline_filled[1:])


def test_no_ink_outside_keeps_original():
    out, how = pr.rescue(_res(P186), _gray([]), lambda pitch: _res(P186))
    assert how is None and [round(x) for x in line_xs(out)] == P186


def test_grid_accepted_only_if_clean_and_overlapping():
    p68 = [368, 550, 625, 730, 912, 1094, 1279, 1457, 1640, 1819]
    fixed = [368, 550, 730, 912, 1094, 1279, 1457, 1640, 1819, 2005]
    out, how = pr.rescue(_res(p68), _gray([]), lambda pitch: _res(fixed))
    assert how == "grid" and [round(x) for x in line_xs(out)] == fixed
    # 网格挑出另一套网（vol20 p179 那样，跟原线几乎不重合）不接受
    far = [1871 + 170 * k for k in range(10)]
    out, how = pr.rescue(_res(p68), _gray([]), lambda pitch: _res(far))
    assert how is None


def test_band_from_distribution():
    """内列 ±10%、外列 0.85–1.3（殿本 2,969 页实测 99.9% 分位）；轻微不匀不算病。"""
    assert pr.in_band([0, 182, 360, 545, 727, 908, 1090, 1272, 1455, 1680])        # 外列 1.23 照收
    assert pr.out_of_band([0, 182, 360, 545, 727, 908, 1090, 1272, 1455, 1700]) == {9}


def test_grid_may_not_move_good_rules():
    """vol13 p46：只有最外一列偏宽（1.3+），网格却把内部三条真界行各挪 9px → 不接受。"""
    old = [343, 523, 700, 876, 1066, 1249, 1440, 1624, 1802, 2040]
    grid = [343, 523, 700, 876, 1066, 1258, 1447, 1635, 1832, 2040]
    bad = pr.out_of_band(old)
    assert bad == {9}
    assert not pr.keeps_good_lines(old, grid, bad)
    out, how = pr.rescue(_res(old), _rules(old), lambda pitch: _res(grid))
    assert how is None


def _rules(xs):
    """每条线处画一道贯通的界行（规范空间 x，原图 x = W−1−x）。"""
    g = np.full((H, W), 255, np.uint8)
    for x in xs:
        g[300:2700, W - 1 - x - 1:W - 1 - x + 2] = 0
    return g


def test_lines_without_rule_evidence_may_move():
    """换图源 vol40 新 p1（卷首大印页）：自由模式在印泥斑点里连挑三条字心线，中间两列宽度碰巧合格；
    这几条线附近没有界行残段，不算真界行，网格探对的网照收。有残段的线照旧护着（上一条测试）。"""
    old = [111, 266, 396, 525, 653, 778, 973, 1099, 1217, 1298]
    grid = [111, 265, 393, 525, 653, 778, 908, 1038, 1168, 1298]
    bad = pr.out_of_band(old)
    assert not pr.keeps_good_lines(old, grid, bad)
    g = _rules(grid[:-1])                        # 真界行在网格线上，自由线 973/1099/1217 处没有
    assert pr.keeps_good_lines(old, grid, bad, ridges=[float(x) for x in grid[:-1]])
    out, how = pr.rescue(_res(old), g, lambda pitch: _res(grid))
    assert how == "grid" and [round(x) for x in line_xs(out)] == grid


def test_fuse_free_grid_and_extrapolated_lines():
    """vol20 p113：c3 里挑了三条错线（真界行淡），网格对上了 c3、c4 却在外侧挑歪；两条路都不成时，
    从自由线＋网格线＋有字一侧的外推外框线里挑一串列宽都在带内的线（自由线优先）。"""
    p113 = [342, 534, 754, 827, 938, 1092, 1279, 1460, 1634, 1830]
    grid = [342, 534, 722, 917, 1092, 1284, 1463, 1656, 1888, 2071]
    g = _gray([(1830, 2011)])                     # 网外那列有字
    out, how = pr.rescue(_res(p113), g, lambda pitch: _res(grid))
    assert how == "fuse"
    xs = [round(x) for x in line_xs(out)]
    assert xs[:2] == [342, 534] and xs[2:4] == [722, 917] and xs[4:9] == [1092, 1279, 1460, 1634, 1830]
    assert 2000 <= xs[9] <= 2030
    assert out.vline_filled == [False] * 9 + [True]
    assert pr.is_clean(xs)


def test_fuse_needs_ink_outside_to_extrapolate():
    p113 = [342, 534, 754, 827, 938, 1092, 1279, 1460, 1634, 1830]
    grid = [342, 534, 722, 917, 1092, 1284, 1463, 1656, 1888, 2071]
    out, how = pr.rescue(_res(p113), _gray([]), lambda pitch: _res(grid))
    assert how is None and [round(x) for x in line_xs(out)] == p113


def test_fuse_takes_rule_stubs_in_head_band():
    """vol16 p8：全页小字雙行，版心里没有界行、只有天头那一截；自由模式把一条界行探偏进字缝（1495）、
    在末列里多挑一条（1874），最右整列落在网外。天头的界行残段补上探偏的线和外框线。"""
    free = [540, 720, 900, 1086, 1265, 1495, 1637, 1812, 1874, 2024]
    true = [353, 539, 718, 897, 1082, 1263, 1448, 1631, 1812, 2030]
    g = _gray([(353, 539)])                       # 网外那列有字
    for x in true:
        g[300:540, W - 1 - x - 1:W - 1 - x + 2] = 0     # 天头的界行残段（240px，> 0.8 列宽）
    out, how = pr.rescue(_res(free), g, lambda pitch: _res(free))
    assert how == "fuse"
    xs = [round(x) for x in line_xs(out)]
    assert all(abs(a - b) <= pr.TOL for a, b in zip(xs, true)), xs     # 自由线对得上的照用自由线
    assert not any(out.vline_filled)


def test_rule_stubs_ignore_char_strokes():
    """字的竖笔（不到一格高）不当界行残段。"""
    g = np.full((H, W), 255, np.uint8)
    g[400:510, W - 1 - 1000] = 0                  # 110px 竖笔
    g[800:1100, W - 1 - 1200] = 0                 # 300px 界行残段
    assert pr._rule_ridges(_res(GOOD), g, 900, 1300, 0.8 * 180, 128) == [1200.0]


#: vol40 p14（v0.5.17 首跑）：版心条印在版框外（规范空间 x 大的一侧），自由模式的右外框线落在框里首列字边上（343，
#: 真版框 314），首列只剩 0.83 列宽
P14 = [343, 497, 679, 866, 1051, 1237, 1421, 1606, 1787, 1973]
P14_FIXED = [314, 497, 679, 866, 1051, 1237, 1421, 1606, 1787, 1973]


def _p14_gray():
    g = _gray([(343, 497), (1973, 2150)])         # 首列有字；版框外版心条也有墨
    for x in (314, 1973, 2150):                   # 版框、版心条边线：贯通整页的界行
        g[300:2700, W - 1 - x - 1:W - 1 - x + 2] = 0
    return g


def test_snap_narrow_outer_col_to_frame():
    """外列偏窄、外侧半列宽内有版框残段：外框线吸到版框上，别的路都不走。"""
    out, how = pr.rescue(_res(P14), _p14_gray(), lambda pitch: (_ for _ in ()).throw(AssertionError("不该重探")))
    assert how == "frame"
    assert all(abs(a - b) <= 2 for a, b in zip(line_xs(out), P14_FIXED))
    assert not any(out.vline_filled)


def test_rescue_may_not_drop_framed_col():
    """吸版框不成时，fuse 外推进版心条、把整网平移一列（首列甩出网外）也不接受（vol46 p118/p148 原病）。"""
    g = _p14_gray()
    shifted = [497, 679, 866, 1051, 1237, 1421, 1606, 1787, 1973, 2157]
    assert pr.drops_framed_col(_res(P14), g, shifted)
    assert not pr.drops_framed_col(_res(P14), g, P14_FIXED)
    assert not pr.drops_framed_col(_res(GOOD), _gray([]), GOOD)


def test_snap_lines_to_faint_rule_and_blank():
    """vol48 p121 形态：界行淡到自由模式探不出，c3 被字缝劈开、末两列并成一列；网格线差 20px 进不了带。
    出带列两边的线吸到淡界行细峰上（没有界行就吸到字间空白中点），列宽进带才收。"""
    free = [329, 513, 693, 775, 873, 1056, 1232, 1418, 1619, 1992]
    grid = [329, 513, 693, 873, 1056, 1232, 1418, 1621, 1778, 1992]
    true = [329, 513, 693, 873, 1056, 1232, 1418, 1597, 1778, 1992]
    g = np.full((H, W), 255, np.uint8)
    for a, b in zip(true, true[1:]):                      # 每列一串字块（字间留白、列间是空白）
        for y in range(400, 2600, 110):
            g[y:y + 80, W - 1 - int(b) + 45:W - 1 - int(a) - 45] = 0
    for x in true[:7] + [1992]:
        g[300:2700, W - 1 - x - 1:W - 1 - x + 2] = 0      # 印得好的界行
    for y in range(300, 2700, 40):
        g[y:y + 12, W - 1 - 1597 - 1:W - 1 - 1597 + 2] = 0  # 淡界行：断成一截截，够不上残段
    out, how = pr.rescue(_res(free), g, lambda pitch: _res(grid))
    assert how == "snap"
    xs = line_xs(out)
    assert abs(xs[7] - 1597) <= 2 and abs(xs[8] - 1778) <= 10, xs
    assert pr.is_clean(xs)
