"""Step1 页级网格模式 `column_grid_pages`（殿本 vol05 p55／p123、vol04 p80 整列漏切，2026-10-19）。"""
from __future__ import annotations

import pytest
from helpers import body_page, make_book, make_ctx

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.border_detect import BorderDetectParams

PAGE = 1


class _Stop(Exception):
    pass


def _grid_kwargs(tmp_path, monkeypatch, params, page=PAGE):
    import open_guji_cv.steps.border_detect as bd
    seen = {}

    def fake(gray, **kw):
        seen.update(kw)
        raise _Stop

    monkeypatch.setattr(bd, "detect_borders", fake)
    ctx = make_ctx(tmp_path, make_book(params=params), raw={page: body_page(n_cols=9)})
    with pytest.raises(_Stop):
        STEPS["border_detect"].run_page(ctx, page)
    return seen


def test_grid_pages_turns_grid_on_for_listed_page(tmp_path, monkeypatch):
    kw = _grid_kwargs(tmp_path, monkeypatch,
                      {"border_detect": {"column_grid_pages": [PAGE], "grid_col_pitch": 185}})
    assert kw["column_grid"] is True and kw["col_pitch"] == 185


def test_grid_pages_other_page_unchanged(tmp_path, monkeypatch):
    kw = _grid_kwargs(tmp_path, monkeypatch,
                      {"border_detect": {"column_grid_pages": [PAGE + 1], "grid_col_pitch": 185}})
    assert kw["column_grid"] is False and kw["col_pitch"] is None


def test_grid_pages_empty_not_in_params_dump():
    d = BorderDetectParams().model_dump()
    assert "column_grid_pages" not in d and "grid_col_pitch" not in d
    d = BorderDetectParams(column_grid_pages=[55], grid_col_pitch=185).model_dump()
    assert d["column_grid_pages"] == [55] and d["grid_col_pitch"] == 185


def _res(xs, width=2300, height=3000):
    from open_guji_cv.seg.frame_types import BorderDetectionResult, HLine, VLine
    h = HLine(y_at_right=300.0, slope=0.0, kind="top")
    return BorderDetectionResult(width=width, height=height, top=h, bottom=h,
                                 verticals=[VLine(x_at_top=float(x), slope=0.0) for x in xs])


def test_pad_outer_columns_widens_narrow_outer_column():
    """殿本 vol04 p63：右框没印全，首列只剩 117px → 按内列中位往外推。"""
    from open_guji_cv.steps.border_detect import pad_outer_columns
    r = _res([380, 497, 679, 862, 1041, 1230, 1416, 1599, 1782, 1963])
    assert pad_outer_columns(r) == 1
    assert round(r.verticals[0].x_at(0)) == 380 - (183 - 117)
    assert r.vline_filled[0] is True and not any(r.vline_filled[1:])
    assert round(r.verticals[-1].x_at(0)) == 1963


def test_pad_outer_columns_leaves_normal_page():
    from open_guji_cv.steps.border_detect import pad_outer_columns
    xs = [423, 602, 784, 970, 1154, 1328, 1515, 1696, 1882, 2060]
    r = _res(xs)
    assert pad_outer_columns(r) == 0
    assert [round(v.x_at(0)) for v in r.verticals] == xs and r.vline_filled == []


def _gray_with_rule(width, height, x_new_rule=None):
    """白底图；给了 x_new_rule（右上原点）就在那里画一条 3px 宽、贯穿框高的细竖线。"""
    import numpy as np
    g = np.full((height, width), 230, np.uint8)
    if x_new_rule is not None:
        xo = (width - 1) - int(x_new_rule)
        g[300:2700, xo - 1:xo + 2] = 20
    return g


def test_trim_outer_columns_snaps_wide_outer_column_to_thin_rule():
    """脉经 02:50：首列把书口圈进来（宽 238）→ 收到内邻线往外一个中位列距附近的细界行上。"""
    from open_guji_cv.steps.border_detect import trim_outer_columns
    xs = [100, 338, 528, 718, 908, 1098, 1288, 1478, 1668, 1858]
    r = _res(xs)
    g = _gray_with_rule(2300, 3000, x_new_rule=150)          # 真内界线：338 − 190 = 148 附近
    assert trim_outer_columns(r, g, 1.12, col_pitch=192) == 1
    assert abs(r.verticals[0].x_at(0) - 150) <= 2
    assert r.vline_filled[0] is False                         # 找到线，不算插值
    assert [round(v.x_at(0)) for v in r.verticals[1:]] == xs[1:]


def test_trim_outer_columns_falls_back_to_median_pitch():
    """末列偏宽、附近没有细线：按中位列距平移，记插值。"""
    from open_guji_cv.steps.border_detect import trim_outer_columns
    xs = [100, 290, 480, 670, 860, 1050, 1240, 1430, 1620, 1880]
    r = _res(xs)
    assert trim_outer_columns(r, _gray_with_rule(2300, 3000), 1.12, col_pitch=192) == 1
    assert round(r.verticals[-1].x_at(0)) == 1620 + 190
    assert r.vline_filled[-1] is True and not any(r.vline_filled[:-1])


def test_trim_outer_columns_off_or_normal_page_unchanged():
    from open_guji_cv.steps.border_detect import trim_outer_columns
    xs = [423, 602, 784, 970, 1154, 1328, 1515, 1696, 1882, 2060]
    r = _res(xs)
    assert trim_outer_columns(r, _gray_with_rule(2300, 3000), 1.12) == 0
    assert trim_outer_columns(r, _gray_with_rule(2300, 3000), 0.0) == 0
    assert [round(v.x_at(0)) for v in r.verticals] == xs and r.vline_filled == []
    assert "grid_outer_trim" not in BorderDetectParams().model_dump()
    assert BorderDetectParams(grid_outer_trim=1.12).model_dump()["grid_outer_trim"] == 1.12


def test_head_raise_scale_passed_through_and_dropped_when_default(tmp_path, monkeypatch):
    """GUJI-748：`head_raise_scale` 传到 detect_borders；缺省 1.0 不进参数 dump（params_hash 与加字段前相同）。"""
    kw = _grid_kwargs(tmp_path, monkeypatch, {"border_detect": {"head_raise_scale": 0.7021}})
    assert kw["head_raise_scale"] == 0.7021
    assert "head_raise_scale" not in BorderDetectParams().model_dump()
    assert BorderDetectParams(head_raise_scale=0.7).model_dump()["head_raise_scale"] == 0.7


def test_grid_lattice_fallback_only_on_grid_pages_and_dropped_when_off(tmp_path, monkeypatch):
    """GUJI-748 vol12 p139：`grid_lattice_fallback` 只在点名网格页传给 detect_borders；
    缺省关不进参数 dump，也不出现在调用参数里（与加字段前的调用一模一样）。"""
    on = {"border_detect": {"column_grid_pages": [PAGE], "grid_col_pitch": 133,
                            "grid_lattice_fallback": True}}
    assert _grid_kwargs(tmp_path / "a", monkeypatch, on)["grid_lattice_fallback"] is True
    other = {"border_detect": {"column_grid_pages": [PAGE + 1], "grid_col_pitch": 133,
                               "grid_lattice_fallback": True}}
    assert "grid_lattice_fallback" not in _grid_kwargs(tmp_path / "b", monkeypatch, other)
    off = {"border_detect": {"column_grid_pages": [PAGE], "grid_col_pitch": 133}}
    assert "grid_lattice_fallback" not in _grid_kwargs(tmp_path / "c", monkeypatch, off)
    assert "grid_lattice_fallback" not in BorderDetectParams().model_dump()
    assert BorderDetectParams(column_grid_pages=[139], grid_lattice_fallback=True
                              ).model_dump()["grid_lattice_fallback"] is True


def _text_page(width, height, x_new_cols, char_w=150):
    """白底图：在给定列心（右上原点 x）画一串 char_w 宽、竖向断续的「字」。"""
    import numpy as np
    g = np.full((height, width), 230, np.uint8)
    for xc in x_new_cols:
        xo = (width - 1) - int(xc)
        for y0 in range(300, 2700, 160):
            g[y0:y0 + 130, xo - char_w // 2:xo + char_w // 2] = 30
    return g


_GF_XS = [100 + 192 * i for i in range(11)]               # 10 列、列距 192
_GF_CENTERS = [x + 96 for x in _GF_XS[:-1]]


def test_gutter_ink_score_low_in_gutters_high_across_text():
    """脉经 02 p15：网格补线整片错半列、斜穿字身 → 穿字分高；线在字缝里 ≈ 0。"""
    from open_guji_cv.steps.border_detect import gutter_ink_score
    g = _text_page(2300, 3000, _GF_CENTERS)
    assert gutter_ink_score(_res(_GF_XS), g) < 0.05
    assert gutter_ink_score(_res([x + 96 for x in _GF_XS]), g) > 0.8
    assert gutter_ink_score(_res([100, 300]), g) == 0.0       # 线太少不量


def _fallback_run(tmp_path, monkeypatch, params, grid_xs, free_xs):
    import open_guji_cv.steps.border_detect as bd
    calls = []

    def fake(gray, **kw):
        calls.append(kw["column_grid"])
        return _res(grid_xs if kw["column_grid"] else free_xs)

    monkeypatch.setattr(bd, "detect_borders", fake)
    monkeypatch.setattr(bd, "pitch_rescue", lambda r, *a, **k: (r, None))
    ctx = make_ctx(tmp_path, make_book(params=params, column_grid=True, col_pitch=192, expected_cols=10),
                   raw={PAGE: _text_page(2300, 3000, _GF_CENTERS)})
    out = STEPS["border_detect"].run_page(ctx, PAGE)
    return calls, out


def test_grid_free_fallback_switches_when_grid_lines_cross_text(tmp_path, monkeypatch):
    calls, out = _fallback_run(tmp_path, monkeypatch, {"border_detect": {"grid_free_fallback": 0.15}},
                               [x + 96 for x in _GF_XS], _GF_XS)
    assert calls == [True, False]
    xs = [round(v.x_at_top) for v in out["borders"].verticals]
    assert xs == _GF_XS
    assert any("grid_free_fallback" in f for ln in out["line_index"].lines for f in ln.flags)


def test_grid_free_fallback_off_or_clean_grid_unchanged(tmp_path, monkeypatch):
    calls, _ = _fallback_run(tmp_path, monkeypatch, {}, [x + 96 for x in _GF_XS], _GF_XS)
    assert calls == [True]                                     # 缺省关：不跑自由模式
    calls, out = _fallback_run(tmp_path, monkeypatch, {"border_detect": {"grid_free_fallback": 0.15}},
                               _GF_XS, [x + 96 for x in _GF_XS])
    assert calls == [True]                                     # 网格线本来就在字缝里：不试
    assert "grid_free_fallback" not in BorderDetectParams().model_dump()
    assert BorderDetectParams(grid_free_fallback=0.15).model_dump()["grid_free_fallback"] == 0.15


def test_grid_free_fallback_keeps_grid_when_free_has_other_line_count(tmp_path, monkeypatch):
    calls, out = _fallback_run(tmp_path, monkeypatch, {"border_detect": {"grid_free_fallback": 0.15}},
                               [x + 96 for x in _GF_XS], _GF_XS[:-1])
    assert calls == [True, False]
    assert [round(v.x_at_top) for v in out["borders"].verticals] == [x + 96 for x in _GF_XS]


def _sliver_page(width=2300, height=3000):
    """脉经 02 p15 的样子：右上原点 x 100 起 10 列字（列距 190），左侧（新坐标大端）粗框条贴着最后一列字外 70px。"""
    import numpy as np
    centers = [195 + 190 * i for i in range(10)]
    g = _text_page(width, height, centers, char_w=140)
    xo = (width - 1) - (100 + 190 * 10 + 70)                  # 粗框条（新坐标 2070 处）
    g[300:2700, xo - 20:xo + 1] = 20
    xo = (width - 1) - 100                                    # 右版框细线（新坐标 100）
    g[300:2700, xo - 1:xo + 2] = 20
    return g


def test_fix_outer_sliver_drops_blank_strip_and_adds_frame_on_other_side():
    from open_guji_cv.steps.border_detect import fix_outer_sliver
    xs = [290 + 190 * i for i in range(10)] + [2070]          # 少认了右框（100），左边多了框条外线（2070）
    r = _res(xs)
    assert fix_outer_sliver(r, _sliver_page(), n_cols=10) == 1
    got = [round(v.x_at(0)) for v in r.verticals]
    assert len(got) == 11 and abs(got[0] - 100) <= 6 and got[-1] == 290 + 190 * 9
    assert r.vline_filled == [False] * 11


def test_fix_outer_sliver_leaves_normal_or_inky_outer_column():
    from open_guji_cv.steps.border_detect import fix_outer_sliver
    xs = [100 + 190 * i for i in range(11)]
    r = _res(xs)
    assert fix_outer_sliver(r, _sliver_page(), n_cols=10) == 0
    assert [round(v.x_at(0)) for v in r.verticals] == xs
    assert fix_outer_sliver(_res(xs[:-1] + [xs[-2] + 60]), _sliver_page(), n_cols=10) == 0   # 窄条里有字：不动
    assert "grid_outer_fix" not in BorderDetectParams().model_dump()
    assert BorderDetectParams(grid_outer_fix=True).model_dump()["grid_outer_fix"] is True


def test_trim_gap_only_keeps_wide_outer_column_with_text_at_target():
    """gap_only：找不到细线、按列距平移的落点压着字，就不收（外列本来就宽、是版框留白）。"""
    from open_guji_cv.steps.border_detect import trim_outer_columns
    xs = [100 + 190 * i for i in range(10)] + [100 + 190 * 9 + 250]
    g = _text_page(2300, 3000, [195 + 190 * i for i in range(9)] + [1910 + 125], char_w=150)
    assert trim_outer_columns(_res(xs), g, 1.12, col_pitch=192, gap_only=True) == 0
    assert trim_outer_columns(_res(xs), g, 1.12, col_pitch=192) == 1


def test_grid_outer_fix_runs_column_fit_in_grid_mode(tmp_path, monkeypatch):
    """grid_outer_fix：网格模式下列宽出带就按版式列数强拟（原先只在自由模式跑）；列宽都在带里不拟。"""
    import open_guji_cv.steps.border_detect as bd
    seen = []
    bad = list(_GF_XS); bad[5] += 45                           # 一条内线偏 45px：两列出带
    for fix, xs, want in ((False, bad, []), (True, _GF_XS, []), (True, bad, [{"n_lines": 11, "keep_guard": False}])):
        seen.clear()
        monkeypatch.setattr(bd, "detect_borders", lambda gray, _xs=xs, **kw: _res(_xs))
        monkeypatch.setattr(bd, "pitch_rescue", lambda r, *a, **k: (seen.append(
            {x: k[x] for x in ("n_lines", "keep_guard") if x in k}), (r, None))[1])
        ctx = make_ctx(tmp_path / f"{fix}{len(seen)}{xs[5]}", make_book(
            params={"border_detect": {"grid_outer_fix": fix}}, column_grid=True, col_pitch=192, expected_cols=10),
            raw={PAGE: _text_page(2300, 3000, _GF_CENTERS)})
        STEPS["border_detect"].run_page(ctx, PAGE)
        assert seen == want


def _edge_page():
    import numpy as np
    H, W = 400, 1200
    g = np.full((H, W), 255, np.uint8)
    g[40:360, 100] = 0                       # 左框线（只在版框内）
    g[40:360, 1060] = 0                      # 右细内框线
    for x in range(1130, 1180, 3):             # 书口条：贯穿天头到页底的一束竖黑条
        g[:, x] = 0
    g[100:300, 200:220] = 0                  # 一块字
    return g


def test_strip_page_edge_erases_edge_stripes_only():
    from open_guji_cv.steps.border_detect import strip_page_edge
    g = _edge_page()
    out, left, right = strip_page_edge(g, 128)
    assert left == 0 and right > 0
    assert (out[:, 1130:] == 255).all()      # 书口条抹掉
    assert (out[40:360, 1060] == 0).all()    # 细框线留着
    assert (out[100:300, 200:220] == 0).all()
    assert (g[:, 1130] == 0).all()           # 不改入参


def test_strip_page_edge_leaves_clean_page_and_param_dropped_when_off():
    import numpy as np
    from open_guji_cv.steps.border_detect import strip_page_edge
    g = np.full((400, 600), 255, np.uint8); g[40:360, 100] = 0
    out, left, right = strip_page_edge(g, 128)
    assert out is g and left == right == 0
    assert "edge_strip" not in BorderDetectParams().model_dump()
    assert BorderDetectParams(edge_strip=True).model_dump()["edge_strip"] is True
