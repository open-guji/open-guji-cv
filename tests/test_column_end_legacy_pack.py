# -*- coding: utf-8 -*-
"""旧产物包重放（CV4 算法待办 #13）：拆步前的包没有 2b `column_bands`，文字带记在 `column_windows.band`。

2c `column_end` 现算列图时按拆步前 `column_warp` 的 `clean_column` 在内存里补算（不带 #1900 `side_cut`），
不写包、不进 `column_banded` 缓存；新包缺 2b 产物仍照旧报「上游产物缺失」。
"""
from __future__ import annotations

import shutil

import numpy as np
import pytest

from helpers import run_keben_from_raw
import open_guji_cv.steps  # noqa: F401  —— 注册 Step 与闸


def _as_legacy_pack(ctx, page: int) -> None:
    """把新链的产物改成拆步前的样子：2b 的带写回 2a 窗口，删掉 2b／2c 的产物与派生缓存。"""
    from open_guji_cv.core.step import STEPS
    bands = ctx.product("column_bands", page)
    wins = ctx.product("column_windows", page)
    cols = [c.model_copy(update={"band": bands.column(c.col).band}) for c in wins.columns]
    ctx.store.write(ctx.book.id, "column_warp", f"p{page:04d}",
                    {"column_windows": wins.model_copy(update={"columns": cols})})
    for sid in ("column_band", "column_end"):
        shutil.rmtree(ctx.store.step_dir(ctx.book.id, sid), ignore_errors=True)
        ctx.store._manifests.pop((ctx.book.id, sid), None)
    for kind in ("column_banded", "column_image"):
        shutil.rmtree(ctx.cache.root / ctx.book.id / kind, ignore_errors=True)
    assert not ctx.has_product("column_bands", page)
    assert "column_band" in STEPS


def test_legacy_pack_column_image_matches_pre_split_clean_column(tmp_path, monkeypatch, keben_book, fixture_page):
    from open_guji_cv.core.spec import column_key
    from open_guji_cv.impl.keben.column import clean_column

    ctx, _ = run_keben_from_raw(tmp_path, monkeypatch, book=keben_book, gray=fixture_page, through="column_end")
    _as_legacy_pack(ctx, 1)
    wins = ctx.product("column_windows", 1)
    assert wins.columns
    fl, og = keben_book.frame_layers or {}, keben_book.outer_gap or {}
    for w in wins.columns:
        key = column_key(1, w.col)
        got = ctx.image("column_image", key)
        # 拆步前 column_warp 的做法：column_raw → clean_column（带与抹界行、削上下端一气做完）
        want, diag = clean_column(
            ctx.image("column_raw", key), ink_threshold=128,
            layers=(int(fl.get("top", 1)), int(fl.get("bottom", 1))),
            layer_gap=(og.get("top"), og.get("bottom")), inner_bottom=w.border_bottom_in_column)
        assert tuple(diag["band"]) == tuple(w.band)
        assert np.array_equal(got, want), key
    # 只在内存里补算：不写 2b 产物、不进 column_banded 缓存
    assert not ctx.has_product("column_bands", 1)
    assert not (ctx.cache.root / ctx.book.id / "column_banded").exists()


def test_new_pack_missing_bands_still_errors(tmp_path, monkeypatch, keben_book, fixture_page):
    """新包（2a 不写 band）缺 2b 产物不当旧包，照旧报上游缺失。"""
    from open_guji_cv.core.spec import column_key

    ctx, _ = run_keben_from_raw(tmp_path, monkeypatch, book=keben_book, gray=fixture_page, through="column_end")
    for sid in ("column_band", "column_end"):
        shutil.rmtree(ctx.store.step_dir(ctx.book.id, sid), ignore_errors=True)
    shutil.rmtree(ctx.cache.root / ctx.book.id / "column_image", ignore_errors=True)
    col = ctx.product("column_windows", 1).columns[0].col
    with pytest.raises(FileNotFoundError, match="column_bands"):
        ctx.image("column_image", column_key(1, col))
