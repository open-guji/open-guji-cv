"""seg.frame_line：整页拟双边版框的内框细线（自造图）。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.seg.frame_line import fit_inner_frame_line


def _page(side: str = "bottom", tilt: float = 0.004, dashed: bool = True, chars: bool = True):
    """造一张 1200 宽的页：外粗框 8 行、离它 12 行一道 3 行厚的内虚线，字脚压在内线上。"""
    h, w = 600, 1200
    ink = np.zeros((h, w), bool)
    rng = np.random.default_rng(1)
    for x in range(50, 1150):
        o = 500 + tilt * (x - 600) if side == "bottom" else 100 + tilt * (x - 600)
        o = int(round(o))
        if side == "bottom":
            ink[o:o + 8, x] = True                       # 外框朝页心一边在 o
            c = o - 12 - 2                                # 内线 3 行：[c, c+3)
        else:
            ink[o - 8:o, x] = True
            c = o + 12 - 1
        if not dashed or (x // 20) % 3 != 2:              # 每 60px 断 20px
            ink[c:c + 3, x] = True
    if chars:   # 字：竖笔一直压到内线上、横笔离线一段
        for cx in range(80, 1150, 110):
            ys = (380, 487) if side == "bottom" else (113, 220)
            ink[ys[0]:ys[1], cx:cx + 6] = True
            ink[ys[0] + 40:ys[0] + 46, cx - 30:cx + 36] = True
    ink |= rng.random((h, w)) < 0.002
    return ink


def test_bottom_inner_line_found_through_dashes_and_touching_strokes():
    ink = _page("bottom")
    line = fit_inner_frame_line(ink, 50, 1150, y_hint=500, cell_h=80, side="bottom")
    assert line is not None
    for x in (100, 600, 1100):
        o = 500 + 0.004 * (x - 600)
        assert abs(float(line.y(x)) - (round(o) - 12.5)) <= 1.0
    assert 2 <= line.thick <= 4
    assert float(line.text_edge(600)) < float(line.y(600))


def test_top_inner_line():
    ink = _page("top")
    line = fit_inner_frame_line(ink, 50, 1150, y_hint=100, cell_h=80, side="top")
    assert line is not None
    assert abs(float(line.y(600)) - 112.5) <= 1.0
    assert float(line.text_edge(600)) > float(line.y(600))


def test_no_frame_returns_none():
    ink = _page("bottom")
    ink[440:, :] = False            # 没有版框
    assert fit_inner_frame_line(ink, 50, 1150, y_hint=500, cell_h=80, side="bottom") is None


def _dotted_page(dot_every: int = 9, tilt: float = 0.004, inner: bool = True):
    """内线磨成点线（每 dot_every px 一个 2px 点），小段里墨占比到不了 RUN_COV，小段投票拟不出。"""
    h, w = 600, 1200
    ink = np.zeros((h, w), bool)
    for x in range(50, 1150):
        o = int(round(500 + tilt * (x - 600)))
        ink[o:o + 8, x] = True
        if inner and x % dot_every < 2:
            c = int(round(500 + 1.6 * tilt * (x - 600))) - 14    # 内线比外框多斜一点
            ink[c:c + 3, x] = True
    for cx in range(80, 1150, 110):                                  # 字竖笔离线一段
        ink[380:470, cx:cx + 6] = True
    return ink


def test_dotted_inner_line_needs_profile_fallback():
    ink = _dotted_page()
    assert fit_inner_frame_line(ink, 50, 1150, y_hint=500, cell_h=80, side="bottom") is None
    line = fit_inner_frame_line(ink, 50, 1150, y_hint=500, cell_h=80, side="bottom", profile_fallback=True)
    assert line is not None and line.via == "profile"
    for x in (150, 600, 1050):
        want = round(500 + 1.6 * 0.004 * (x - 600)) - 14 + 1
        assert abs(float(line.y(x)) - want) <= 1.0
    assert 2 <= line.thick <= 4


def test_profile_fallback_keeps_chunk_result():
    ink = _page("bottom")
    a = fit_inner_frame_line(ink, 50, 1150, y_hint=500, cell_h=80, side="bottom")
    b = fit_inner_frame_line(ink, 50, 1150, y_hint=500, cell_h=80, side="bottom", profile_fallback=True)
    assert a == b and a.via == "chunks"


def test_profile_fallback_no_inner_line():
    ink = _dotted_page(inner=False)
    assert fit_inner_frame_line(ink, 50, 1150, y_hint=500, cell_h=80, side="bottom", profile_fallback=True) is None


def _bent_page():
    """高分辨率页（格高 200）：外框 40 行厚、右端 300px 上翘 40 行；内线 9 行厚、离外框 30 行，跟着外框翘；
    字的底横离外框 70 行。整页二次曲线跟不上右端的翘，线心落到外框上沿。"""
    h, w = 1200, 2400
    ink = np.zeros((h, w), bool)
    for x in range(100, 2300):
        o = 1000 - (max(0, x - 2000) * 40 / 300.0)
        o = int(round(o))
        ink[o:o + 40, x] = True
        ink[o - 39:o - 30, x] = True          # 内线 9 行：[o-39, o-30)
    for cx in range(150, 2000, 210):        # 字底横（不伸进右端翘起段：翘到 x≈2280 时内线会和字底横叠在一起，真页上不会有）
        ink[920:927, cx:cx + 120] = True
        ink[700:927, cx + 55:cx + 63] = True
    return ink


def test_localize_follows_bent_frame_and_thick_line():
    from open_guji_cv.seg.frame_line import inner_thick_limit, localize_inner_line
    ink = _bent_page()
    mt = inner_thick_limit(200)
    assert mt > 9
    line = fit_inner_frame_line(ink, 100, 2300, y_hint=1000, cell_h=200, side="bottom", max_thick=mt)
    assert line is not None
    loc = localize_inner_line(ink, line, 200, max_thick=mt)
    assert loc.knots
    for x in (300, 1200, 1900, 2150, 2280):
        o = 1000 - (max(0, x - 2000) * 40 / 300.0)
        assert abs(float(loc.y(x)) - (round(o) - 34.5)) <= 2.0, x
    # 字底横（离外框 70 行）不能被认成内线
    assert all(abs(float(loc.y(x)) - 923) > 20 for x in range(150, 2000, 210))


def test_localize_no_frame_keeps_line():
    from open_guji_cv.seg.frame_line import localize_inner_line
    ink = _page("bottom")
    line = fit_inner_frame_line(ink, 50, 1150, y_hint=500, cell_h=80, side="bottom")
    ink2 = np.zeros_like(ink)
    assert localize_inner_line(ink2, line, 80) is line


def test_seed_fallback_for_broken_inner_line():
    """内线断续（只剩四成小段看得见）、空段验线过不了时，种子线＋逐段贴线仍贴得上。"""
    from open_guji_cv.seg.frame_line import inner_thick_limit, localize_inner_line
    ink = _bent_page()
    for x in range(100, 2300):
        if (x // 60) % 5 >= 2:              # 每 300px 只留 120px 内线
            ink[1000 - int(max(0, x - 2000) * 40 / 300.0) - 39:1000 - int(max(0, x - 2000) * 40 / 300.0) - 30, x] = False
    mt = inner_thick_limit(200)
    line = fit_inner_frame_line(ink, 100, 2300, y_hint=1000, cell_h=200, side="bottom", max_thick=mt,
                                seed_fallback=True)
    assert line is not None
    loc = localize_inner_line(ink, line, 200, max_thick=mt)
    assert loc.knots
    for x in (300, 1200, 2150):
        o = 1000 - (max(0, x - 2000) * 40 / 300.0)
        assert abs(float(loc.y(x)) - (round(o) - 34.5)) <= 3.0, x


# ── profile_fit2（cell_shrink.inner_frame_fit2，2026-11-08）──────────────
def _thick_page():
    """格高约 111 的页：内线印得粗（10 行），超过细线上限 7 行；字竖笔离线一段。"""
    h, w = 800, 1200
    ink = np.zeros((h, w), bool)
    for x in range(50, 1150):
        o = int(round(700 + 0.003 * (x - 600)))
        ink[o:o + 14, x] = True                       # 外粗框比内线还厚
        ink[o - 26:o - 16, x] = True
    for cx in range(80, 1150, 110):
        ink[520:660, cx:cx + 6] = True
    return ink


def test_thick_inner_line_needs_fit2():
    ink = _thick_page()
    assert fit_inner_frame_line(ink, 50, 1150, y_hint=700, cell_h=111, side="bottom", profile_fallback=True) is None
    line = fit_inner_frame_line(ink, 50, 1150, y_hint=700, cell_h=111, side="bottom", profile_fallback=True,
                                profile_fit2=True)
    assert line is not None and line.via == "profile" and 9 <= line.thick <= 11
    assert abs(float(line.text_edge(600)) - (700 - 26)) <= 1.5


def _ruled_dotted_page():
    """点线内线（每 9px 一个 2px 点）＋每 110px 一道界行竖到内线：界行把底子垫高，不剔掉量不出半高宽。"""
    h, w = 600, 1200
    ink = np.zeros((h, w), bool)
    for x in range(50, 1150):
        o = int(round(500 + 0.004 * (x - 600)))
        ink[o:o + 8, x] = True
        if x % 9 < 2:
            ink[o - 15:o - 12, x] = True
    for cx in range(60, 1150, 110):
        o = int(round(500 + 0.004 * (cx - 600)))
        ink[150:o - 12, cx:cx + 14] = True                         # 界行
        ink[400:o - 16, cx + 40:cx + 60] = True                    # 字脚压近线
    return ink


def test_ruled_dotted_inner_line_needs_rule_mask():
    ink = _ruled_dotted_page()
    assert fit_inner_frame_line(ink, 50, 1150, y_hint=500, cell_h=80, side="bottom", profile_fallback=True) is None
    line = fit_inner_frame_line(ink, 50, 1150, y_hint=500, cell_h=80, side="bottom", profile_fallback=True,
                                profile_fit2=True)
    assert line is not None and line.via == "profile"
    assert abs(float(line.y(600)) - (500 - 14)) <= 1.5
