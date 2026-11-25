# -*- coding: utf-8 -*-
"""column_warp.render 再生列图前对照产物 column_windows：尺寸／削边对不上就报错（框型配置改了而产物没重跑）。

冷缓存下游按产物里的格坐标裁再生的列图，配置在产物之后变过就会裁偏（殿本 vol21 p76 c1 高 2466→2436）。
合成页 + 自备册，不依赖真书数据。"""
from __future__ import annotations

import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401
from helpers import blank_page, make_book, make_borders, make_ctx, make_gate1
from open_guji_cv.core.step import STEPS
from open_guji_cv.core.spec import column_key

PAGE = 1
NCOLS = 9


def _ran(tmp_path):
    ctx = make_ctx(tmp_path, make_book(expected_cols=NCOLS), raw={PAGE: blank_page()})
    pk = f"p{PAGE:04d}"
    ctx.store.write(ctx.book.id, "border_detect", pk, {"borders": make_borders(n_cols=NCOLS)})
    ctx.store.write(ctx.book.id, "border_detect_gate", pk,
                    {"border_detect_gate_manifest": make_gate1(PAGE, n_cols=NCOLS, expected_cols=NCOLS)})
    out = STEPS["column_warp"].run_page(ctx, PAGE)
    ctx.store.write(ctx.book.id, "column_warp", pk, out)
    return ctx, out["column_windows"]


def test_render_matches_product(tmp_path):
    ctx, wins = _ran(tmp_path)
    col = wins.columns[0].col
    step = STEPS["column_warp"]
    img = step.render(ctx, "column_image", column_key(PAGE, col))
    assert (img.shape[1], img.shape[0]) == tuple(wins.columns[0].warped_size)


def test_render_refuses_when_size_differs(tmp_path):
    ctx, wins = _ran(tmp_path)
    rec = wins.columns[0]
    rec.warped_size = (rec.warped_size[0], rec.warped_size[1] + 30)      # 产物是别的配置下出的
    ctx.store.write(ctx.book.id, "column_warp", f"p{PAGE:04d}", {"column_windows": wins})
    with pytest.raises(RuntimeError, match="对不上"):
        STEPS["column_warp"].render(ctx, "column_image", column_key(PAGE, rec.col))


def test_render_skips_check_without_product(tmp_path):
    ctx, wins = _ran(tmp_path)
    ctx2 = make_ctx(tmp_path / "b", make_book(expected_cols=NCOLS), raw={PAGE: blank_page()})
    pk = f"p{PAGE:04d}"
    ctx2.store.write(ctx2.book.id, "border_detect", pk, {"borders": make_borders(n_cols=NCOLS)})
    ctx2.store.write(ctx2.book.id, "border_detect_gate", pk,
                     {"border_detect_gate_manifest": make_gate1(PAGE, n_cols=NCOLS, expected_cols=NCOLS)})
    img = STEPS["column_warp"].render(ctx2, "column_image", column_key(PAGE, wins.columns[0].col))
    assert isinstance(img, np.ndarray)
