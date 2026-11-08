# -*- coding: utf-8 -*-
"""`border_detect.bend_w80_med`（2026-11-08，殿本第7轮 Commons 图源列端切半）：书级弯页门槛，写 0＝整页三段折线。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.books.siku_zongmu.border import detect_borders
from open_guji_cv.seg.frame_types import HLine, VLine
from open_guji_cv.seg.polyline import fit_vlines_polyline
from open_guji_cv.steps.border_detect import BorderDetectParams


def _straight_page(w=1400, h=2400, n_cols=6, top_y=300, bot_y=2100):
    """合成直线页：界行竖直、版框水平（w80 中位远小于 BEND_W80_MED）。"""
    mask = np.zeros((h, w), dtype=np.float64)
    xs = np.linspace(200, w - 200, n_cols + 1)
    for x in xs:
        xo = (w - 1) - int(round(x))
        mask[top_y:bot_y, xo - 2:xo + 3] = 1.0
    mask[top_y:top_y + 5, :] = 1.0
    mask[bot_y - 5:bot_y, :] = 1.0
    top = HLine(y_at_right=float(top_y + 2), slope=0.0, kind="top")
    bottom = HLine(y_at_right=float(bot_y - 2), slope=0.0, kind="bottom")
    verts = [VLine(x_at_top=float(x), slope=0.0) for x in xs]
    return mask, top, bottom, verts, xs


def test_default_not_in_params_dump():
    """缺省 None 不进参数 dump：没配的书 params_hash 与加字段前相同。"""
    assert "bend_w80_med" not in BorderDetectParams().model_dump()
    assert BorderDetectParams(bend_w80_med=0).model_dump()["bend_w80_med"] == 0


def test_zero_threshold_forces_three_segments_on_straight_page():
    mask, top, bottom, verts, xs = _straight_page()
    _, seg, w80m, _ = fit_vlines_polyline(mask, top, bottom, list(verts), 1400, 2400)
    assert seg == 1 and w80m is not None and w80m < 7
    out, seg, w80m0, _ = fit_vlines_polyline(mask, top, bottom, list(verts), 1400, 2400, w80_med_min=0)
    assert seg == 3 and w80m0 == w80m
    assert all(v.segments == 3 for v in out)
    for v, x in zip(out, xs):          # 直线页上的折线仍贴着真线
        for y in (300.0, 900.0, 1500.0, 2100.0):
            assert abs(v.x_at(y) - x) <= 2


def test_none_threshold_is_module_constant():
    mask, top, bottom, verts, _ = _straight_page()
    a = fit_vlines_polyline(mask, top, bottom, list(verts), 1400, 2400)
    b = fit_vlines_polyline(mask, top, bottom, list(verts), 1400, 2400, w80_med_min=None)
    assert a[1:] == b[1:] and [(v.x_at_top, v.slope, v.k2) for v in a[0]] == [(v.x_at_top, v.slope, v.k2) for v in b[0]]


def test_fit_false_still_wins():
    mask, top, bottom, verts, _ = _straight_page()
    _, seg, _, _ = fit_vlines_polyline(mask, top, bottom, list(verts), 1400, 2400, fit=False, w80_med_min=0)
    assert seg == 1


def test_detect_borders_passes_threshold_through():
    mask, *_ = _straight_page()
    gray = np.where(mask > 0, 0, 255).astype(np.uint8)
    assert detect_borders(gray, expected_cols=6).vline_segments == 1
    res = detect_borders(gray, expected_cols=6, bend_w80_med=0)
    assert res.vline_segments == 3 and all(v.segments == 3 for v in res.verticals)
