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


def test_default_on_in_params_dump():
    assert BorderDetectParams().model_dump()["vline_track"] is True          # 11-25 起缺省开
    assert BorderDetectParams(vline_track=False).model_dump()["vline_track"] is False


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


def _gray_faint(xfn, depth=25.0, chars=True):
    """淡线页灰度图：底 200，线比底暗 depth（二值化 <128 看不见）；线两侧每 120px 一块黑字。"""
    g = np.full((H, W), 200.0)
    for y in range(TOP, BOT):
        x = xfn(y)
        xi = int(round(x))
        g[y, xi - 2:xi + 3] -= depth
        if chars and (y // 120) % 2 == 0:
            g[y, int(x) + 25:int(x) + 70] = 20.0
            g[y, int(x) - 70:int(x) - 25] = 20.0
    g[TOP:TOP + 5, :] = 20.0
    g[BOT - 5:BOT, :] = 20.0
    return g.astype(np.uint8)


def test_faint_line_found_by_gray_fallback():
    """二值图里没有这条线（逐行追不到），给了灰度就按暗度分段找回来：斜 20px 的淡线。"""
    xfn = lambda y: 600.0 + 20.0 * (y - TOP) / (BOT - TOP)
    g = _gray_faint(xfn)
    m = (g < 128).astype(np.float64)
    top, bottom = _lines()
    out, n = refit_vlines_by_track(m, top, bottom, [_v(600.0)], W, H)
    assert n == 0                                    # 不给灰度：追不到，不动
    out, n = refit_vlines_by_track(m, top, bottom, [_v(600.0)], W, H, gray=g)
    assert n == 1
    for y in (300.0, 1300.0, 2300.0):            # 分段按 0.5px 平移取样，斜线会有 1–2px 系统偏；< 5px 算准
        assert abs(((W - 1) - out[0].x_at(y)) - xfn(y)) <= 3


def test_no_faint_line_stays_put():
    """灰度里也没有线（只有字）：兜底不动现线。"""
    g = _gray_faint(lambda y: 600.0, depth=0.0)
    m = (g < 128).astype(np.float64)
    top, bottom = _lines()
    out, n = refit_vlines_by_track(m, top, bottom, [_v(600.0)], W, H, gray=g)
    assert n == 0


def test_gray_fallback_page_shorter_than_frame():
    """页图比上下框矮（汉书 26 册 p5：合扫拆坏的 120px 窄条，2026-11-27）：淡线兜底不越界抛 IndexError。"""
    h = 120
    m = np.zeros((h, W), dtype=np.float64)
    gray = np.full((h, W), 230, dtype=np.uint8)
    gray[:, 598:602] = 120                       # 一条淡竖线（mask 里没有，走灰度兜底）
    top = HLine(y_at_right=10.0, slope=0.0, kind="top")
    bottom = HLine(y_at_right=float(h + 300), slope=0.0, kind="bottom")   # 下框落在图外
    out, _n = refit_vlines_by_track(m, top, bottom, [_v(600.0)], W, h, gray=gray)
    assert len(out) == 1
