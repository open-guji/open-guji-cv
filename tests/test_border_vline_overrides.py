# -*- coding: utf-8 -*-
"""`border_detect.vline_overrides`（2026-11-02，史記文淵閣本 06 p63、04 p120/p122）：页级人核界行。"""
from __future__ import annotations

from open_guji_cv.seg.frame_types import BorderDetectionResult, HLine, VLine
from open_guji_cv.steps.border_detect import BorderDetectParams, _apply_vline_override


def test_default_not_in_params_dump():
    """缺省空：不进参数 dump，没配的书产物指纹不变。"""
    assert "vline_overrides" not in BorderDetectParams().model_dump()
    assert BorderDetectParams(vline_overrides={63: [0.0, 100.0]}).model_dump()["vline_overrides"] == {63: [0.0, 100.0]}


def _res(xs):
    top, bot = HLine(100.0, 0.0, "top"), HLine(900.0, 0.0, "bottom")
    vs = [VLine(x, 0.0) for x in xs]
    return BorderDetectionResult(width=1000, height=1000, top=top, bottom=bot, verticals=vs,
                                 vline_filled=[False] * len(vs), vline_segments=3)


def test_override_replaces_lines_sorted_and_straight():
    res = _res([167, 275, 363, 562])
    _apply_vline_override(res, [562, 0, 167, 363])
    assert [round(v.x_at(500.0)) for v in res.verticals] == [0, 167, 363, 562]
    assert res.vline_segments == 1 and res.vline_filled == [False] * 4
    assert all(v.k2 is None for v in res.verticals)
