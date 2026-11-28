# -*- coding: utf-8 -*-
"""`border_detect.outer_bar`（2026-11-24）：左右外框线先找粗外框条、再找内框细线，细线磨没处按粗条内沿 − 间距补。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.impl.keben.border import refit_outer_by_bar
from open_guji_cv.seg.frame_types import HLine, VLine
from open_guji_cv.steps.border_detect import BorderDetectParams

W, H, TOP, BOT = 1400, 2600, 200, 2400
GAP, BAR_W = 22, 26


def _page(worn=(900, 1900), drift=12.0, thin_bend=True):
    """旧坐标（左上原点）的墨图。左外框：粗条 + 内侧细线，两者一起往右弯 drift px（下半页）；
    细线在 worn 区间磨没。内部界行竖直。"""
    m = np.zeros((H, W), dtype=np.float64)
    xs_inner = np.linspace(300, 1100, 6)
    for y in range(TOP, BOT):
        s = drift * max(0.0, (y - 1300) / (BOT - 1300))
        xl = 150 + s                                   # 左外框细线
        m[y, int(xl - GAP - BAR_W):int(xl - GAP)] = 1  # 粗条（细线外侧）
        if not (worn[0] <= y < worn[1]):
            m[y, int(xl) - 2:int(xl) + 2] = 1
        for x in xs_inner:
            m[y, int(x) - 2:int(x) + 2] = 1
        m[y, 1250 - 2:1250 + 2] = 1                    # 右外框细线（没有粗条）
    m[TOP:TOP + 5, :] = 1
    m[BOT - 5:BOT, :] = 1
    return m


def _verts(x_left: float):
    """新坐标（x 从右往左）的直线：右框线 1250、内部界行、左框线 x_left。"""
    xs_old = [1250.0] + list(np.linspace(1100, 300, 6)) + [x_left]
    return [VLine(x_at_top=(W - 1) - x, slope=0.0) for x in xs_old]


def _lines():
    top = HLine(y_at_right=float(TOP + 2), slope=0.0, kind="top")
    bottom = HLine(y_at_right=float(BOT - 2), slope=0.0, kind="bottom")
    return top, bottom


def test_default_on_in_params_dump():
    assert BorderDetectParams().model_dump()["outer_bar"] is True            # 11-25 起缺省开
    assert BorderDetectParams(outer_bar=False).model_dump()["outer_bar"] is False


def test_worn_thin_line_follows_bar():
    """现线贴在粗条内沿上（细线大半磨没时算法的典型错误），按粗条内沿 + 间距拉回细线。"""
    m = _page(worn=(400, 2300))
    top, bottom = _lines()
    verts = _verts(150 - GAP)                          # 现线 = 粗条内沿
    out, n = refit_outer_by_bar(m, top, bottom, verts, W, H)
    assert n == 1
    v = out[-1]
    for y in (500.0, 1300.0, 2300.0):
        want = 150 + 12.0 * max(0.0, (y - 1300) / (BOT - 1300))
        assert abs(((W - 1) - v.x_at(y)) - want) <= 3, y


def test_line_on_visible_thin_line_untouched():
    """细线清楚、现线压在细线上：不动（位置不变）。"""
    m = _page(worn=(0, 0), drift=0.0)
    top, bottom = _lines()
    verts = _verts(150.0)
    out, _ = refit_outer_by_bar(m, top, bottom, verts, W, H)
    for y in (300.0, 1300.0, 2300.0):
        assert abs(((W - 1) - out[-1].x_at(y)) - 150.0) <= 1


def test_side_without_bar_untouched():
    m = _page()
    top, bottom = _lines()
    verts = _verts(150.0)
    out, _ = refit_outer_by_bar(m, top, bottom, verts, W, H)
    assert out[0] is verts[0]                          # 右框线没有粗条


def test_outer_side_limits_to_declared_side():
    m = _page(worn=(400, 2300))
    top, bottom = _lines()
    verts = _verts(150 - GAP)
    out, n = refit_outer_by_bar(m, top, bottom, verts, W, H, outer_side="right")
    assert n == 0 and out[-1] is verts[-1]


def test_skip_sides_keeps_bar_line():
    """册声明该侧单线（frame_layers 左/右=1，四周單邊）：粗条就是版框，不按粗条内沿补内框。"""
    m = _page(worn=(400, 2300))
    top, bottom = _lines()
    verts = _verts(150 - GAP)
    out, n = refit_outer_by_bar(m, top, bottom, verts, W, H, skip_sides=("left",))
    assert n == 0 and out[-1] is verts[-1]
    _, n2 = refit_outer_by_bar(m, top, bottom, verts, W, H, skip_sides=("right",))
    assert n2 == 1                                     # 声明另一侧不影响这一侧
