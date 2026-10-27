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
    from open_guji_cv.utils.border_geometry import BorderDetectionResult, HLine, VLine
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
