"""Step1 页级网格模式 `column_grid_pages`（殿本 vol05 p55／p123、vol04 p80 整列漏切，2026-10-19）。"""
from __future__ import annotations

import pytest

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from helpers import body_page, make_book, make_ctx
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
