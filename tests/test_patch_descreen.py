# -*- coding: utf-8 -*-
"""cell_shrink.patch_descreen_pages：缺省关、不进参数 dump；开了才对登记页的字块去网点（SJ 半色调页，2026-11-03）。"""
import numpy as np

from open_guji_cv.steps.cell_shrink import CellShrinkParams
from open_guji_cv.utils.preclean import descreen


def test_default_off_not_in_dump():
    d = CellShrinkParams().model_dump()
    assert not any(k.startswith("patch_descreen") for k in d)


def test_on_in_dump():
    d = CellShrinkParams(patch_descreen_pages=[106]).model_dump()
    assert d["patch_descreen_pages"] == [106] and d["patch_descreen_sigma"] == 0.8


def test_descreen_merges_halftone_stroke():
    # 一条「网点」竖笔：隔点黑白交错的 1-bit 条带，低通重二值后应连成实心的墨
    g = np.full((40, 40), 255, np.uint8)
    for y in range(40):
        for x in range(18, 24):
            if (x + y) % 2 == 0:
                g[y, x] = 0
    out = descreen(g)
    assert set(np.unique(out)) <= {0, 255}
    assert (out[:, 19:23] == 0).mean() > 0.9
    assert (out[:, :10] == 255).all()
