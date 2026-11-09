# -*- coding: utf-8 -*-
"""`border_detect.hline_hints`（2026-11-09，GUJI-758 殿本上版框认错页）：页级人给上／下版框 y。"""
from __future__ import annotations

import numpy as np
import pytest

from open_guji_cv.seg.lines import find_horizontal_border
from open_guji_cv.steps.border_detect import BorderDetectParams


def test_default_not_in_params_dump():
    """缺省空：不进参数 dump，没配的书产物指纹不变。"""
    assert "hline_hints" not in BorderDetectParams().model_dump()
    p = BorderDetectParams(hline_hints={"156": {"top": 190}})
    assert p.model_dump()["hline_hints"] == {156: {"top": 190.0}}


def _page():
    """抬头框贴图顶：图顶 y=5 一条横墨（抬头框顶），真框条 y=150–160、内沿细线 y=185，都略斜。"""
    h, w = 1200, 900
    m = np.zeros((h, w))
    xs = np.arange(w)
    for y0, th in ((5, 8), (150, 10), (185, 2)):
        for dy in range(th):
            ys = np.round(y0 + dy + 0.004 * (xs - w / 2)).astype(int)
            m[ys, xs] = 1.0
    return m


def test_hint_takes_position_and_bar_slope():
    m = _page()
    r = find_horizontal_border(m, "top", hint=186.0)
    assert r.position == 186.0
    assert r.slope == pytest.approx(0.004, abs=0.0006)


def test_hint_blank_band_is_level():
    r = find_horizontal_border(np.zeros((1200, 900)), "top", hint=300.0)
    assert (r.position, r.slope) == (300.0, 0.0)
