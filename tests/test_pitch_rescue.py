# -*- coding: utf-8 -*-
"""列距救援（Step1 后处理，`utils/pitch_rescue`）：列网里多挑一条假竖线、外侧整列落到网外时按列距重定。

纯内存构造：竖线位置取殿本 vol14 p186、vol20 p68 的真页形态（数是形态，不是 fixture 文件）。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.utils.border_geometry import BorderDetectionResult, HLine, VLine
from open_guji_cv.utils.column_pair_merge import line_xs
from open_guji_cv.utils import pitch_rescue as pr

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
