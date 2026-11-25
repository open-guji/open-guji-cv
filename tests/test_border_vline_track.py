# -*- coding: utf-8 -*-
"""`border_detect.vline_track`（2026-11-25）：竖线逐条追细墨，先直线、贴不住再自由折点三段折线；磨没的线不动。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.impl.keben.border import refit_vlines_by_track
from open_guji_cv.seg.frame_types import HLine, VLine
from open_guji_cv.steps.border_detect import BorderDetectParams

W, H, TOP, BOT = 1400, 2600, 200, 2400


def _lines():
    top = HLine(y_at_right=float(TOP + 2), slope=0.0, kind="top")
    bottom = HLine(y_at_right=float(BOT - 2), slope=0.0, kind="bottom")
    return top, bottom


def _x_bent(y):
    """旧坐标里一条下半段往右弯 15px 的线（y=1300 处起折，斜率 0.0136）。"""
    return 600.0 + 15.0 * max(0.0, (y - 1300) / (BOT - 1300))


def _page(xfn, worn=None, wide_at=None):
    m = np.zeros((H, W), dtype=np.float64)
    for y in range(TOP, BOT):
        if worn is None or not (worn[0] <= y < worn[1]):
            x = xfn(y)
            m[y, int(x) - 2:int(x) + 2] = 1
        if wide_at is not None and wide_at[0] <= y < wide_at[1]:
            m[y, 560:590] = 1                    # 线左侧 10px 外一块宽墨（鱼尾）
            m[y, 590:592] = 1                    # 宽墨边上的碎墨
    m[TOP:TOP + 5, :] = 1
    m[BOT - 5:BOT, :] = 1
    return m


def _v(x_old: float) -> VLine:
    return VLine(x_at_top=(W - 1) - x_old, slope=0.0)


def test_default_not_in_params_dump():
    assert "vline_track" not in BorderDetectParams().model_dump()
    assert BorderDetectParams(vline_track=True).model_dump()["vline_track"] is True


def test_straight_line_stays_straight():
    m = _page(lambda y: 600.0)
    top, bottom = _lines()
    out, n = refit_vlines_by_track(m, top, bottom, [_v(603.0)], W, H)
    assert n == 1
    assert out[0].segments == 1
    for y in (300.0, 1300.0, 2300.0):
        assert abs(((W - 1) - out[0].x_at(y)) - 600.0) <= 1


def test_bent_line_gets_polyline():
    m = _page(_x_bent)
    top, bottom = _lines()
    out, n = refit_vlines_by_track(m, top, bottom, [_v(600.0)], W, H)
    assert n == 1 and out[0].segments == 3
    for y in (300.0, 1300.0, 1900.0, 2350.0):
        assert abs(((W - 1) - out[0].x_at(y)) - _x_bent(y)) <= 1.5, y


def test_worn_line_untouched():
    """细线大半磨没（只剩 20%）：支撑不足，不动现线。"""
    m = _page(lambda y: 600.0, worn=(400, 2300))
    top, bottom = _lines()
    v = _v(610.0)
    out, n = refit_vlines_by_track(m, top, bottom, [v], W, H)
    assert n == 0 and out[0] is v


def test_fragments_beside_wide_ink_ignored():
    """线旁有宽墨（鱼尾）的一段，宽墨边上的碎墨不把线拉过去。"""
    m = _page(lambda y: 600.0, wide_at=(900, 1300))
    top, bottom = _lines()
    out, _ = refit_vlines_by_track(m, top, bottom, [_v(600.0)], W, H)
    for y in (1000.0, 1200.0):
        assert abs(((W - 1) - out[0].x_at(y)) - 600.0) <= 1


def test_override_chord_slope():
    """人核界行（vline_overrides）借斜率：开 vline_track 时借弦斜率，不借折线第一段斜率。"""
    from types import SimpleNamespace
    from open_guji_cv.steps.border_detect import _apply_vline_override
    top, bottom = _lines()
    bent = VLine(x_at_top=500.0, slope=0.02, k2=0.0, k3=0.0, y1=800.0, y2=1600.0)   # 第一段斜，后两段直
    res = SimpleNamespace(top=top, bottom=bottom, height=H, verticals=[bent])
    _apply_vline_override(res, [520.0], chord_slope=True)
    v = res.verticals[0]
    chord = (bent.x_at(float(BOT - 2)) - bent.x_at(float(TOP + 2))) / (BOT - 2 - TOP - 2)
    assert abs(v.slope - chord) < 1e-9
    res = SimpleNamespace(top=top, bottom=bottom, height=H, verticals=[bent])
    _apply_vline_override(res, [520.0])
    assert res.verticals[0].slope == 0.02                                          # 缺省行为不变


def test_three_segment_page_stays_uniform():
    """三段页上换成直线的线也写成三段格式。"""
    from open_guji_cv.impl.keben.border import _bend_verticals
    m = _page(lambda y: 600.0)
    for y in range(TOP, BOT):
        x = _x_bent(y) + 300
        m[y, int(x) - 2:int(x) + 2] = 1
    top, bottom = _lines()
    straight = [_v(900.0), _v(600.0)]
    out, vseg, *_ = _bend_verticals(m, (m > 0).astype(np.uint8), top, bottom, straight, W, H, True,
                                    bend_w80_med=0.0, vline_track=True)
    if vseg == 3:
        assert all(v.segments == 3 for v in out)
