# -*- coding: utf-8 -*-
"""冷缓存再生列图的护栏（2026-11-25，CV4→CV0 殿本 frame_layers／outer_gap）。

改了册配置（book_deps 字段）而没重跑 column_warp 时，`render` 按**现**配置再生的列图跟**旧**产物的窗口、
`warped_size`、下游格坐标对不上；下游按旧坐标裁新图就裁偏（ZM replay-1125 二→一 37 格）。钉三条：
1. 产物 manifest 记的 book_deps 取值与现配置不同 → `materialize` 报 `StaleRenderError`，不现算；
2. 再生列图尺寸与产物 `warped_size` 不同 → `column_warp.render` 报错；
3. `cell_shrink` 的整页内框线记忆带产物戳，产物换了不串。
"""

from __future__ import annotations

import dataclasses

import pytest

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from helpers import blank_page, make_book, make_borders, make_ctx, make_gate1
from open_guji_cv.core.engine import book_dep_values
from open_guji_cv.core.spec import column_key
from open_guji_cv.core.step import STEPS, StaleRenderError
from open_guji_cv.products.manifest import ManifestEntry

PAGE = 1
NCOLS = 9


def _ctx(tmp_path, book=None):
    ctx = make_ctx(tmp_path, book or make_book(expected_cols=NCOLS), raw={PAGE: blank_page()})
    ctx.store.write(ctx.book.id, "border_detect", f"p{PAGE:04d}", {"borders": make_borders(n_cols=NCOLS)})
    ctx.store.write(ctx.book.id, "border_detect_gate", f"p{PAGE:04d}",
                    {"border_detect_gate_manifest": make_gate1(PAGE, n_cols=NCOLS, expected_cols=NCOLS)})
    return ctx


def _run_warp(ctx, book_at_run):
    """按 `book_at_run` 的配置跑 column_warp 这一页，写产物与 manifest（含 book_deps 原值），清掉缓存图。"""
    step = STEPS["column_warp"]
    out = step.run_page(ctx, PAGE)
    _, sha = ctx.store.write(ctx.book.id, "column_warp", f"p{PAGE:04d}", out)
    ctx.store.manifest(ctx.book.id, "column_warp").put(ManifestEntry(
        key=f"p{PAGE:04d}", fingerprint="x", sha256=sha, status="ok",
        book=book_dep_values(step, book_at_run)))
    ctx.cache.invalidate(ctx.book.id, "column_image")
    ctx.cache.invalidate(ctx.book.id, "column_raw")
    return out


def test_render_same_config_ok(tmp_path):
    ctx = _ctx(tmp_path)
    _run_warp(ctx, ctx.book)
    img = ctx.image("column_image", column_key(PAGE, 1))
    assert img.ndim == 2


def test_render_refuses_when_book_deps_changed(tmp_path):
    ctx = _ctx(tmp_path)
    _run_warp(ctx, ctx.book)
    ctx.book = dataclasses.replace(ctx.book, frame_layers={"top": 2, "bottom": 2}, outer_gap={"top": 20.0, "bottom": 20.0})
    with pytest.raises(StaleRenderError, match="frame_layers"):
        ctx.image("column_image", column_key(PAGE, 1))


def test_old_manifest_without_book_not_checked(tmp_path):
    """老条目没记 book（2026-09-28 之前）→ 无从比对，照旧放行。"""
    ctx = _ctx(tmp_path)
    _run_warp(ctx, ctx.book)
    m = ctx.store.manifest(ctx.book.id, "column_warp")
    ent = m.get(f"p{PAGE:04d}")
    m.put(dataclasses.replace(ent, book=None))
    ctx.book = dataclasses.replace(ctx.book, frame_layers={"top": 2})
    assert ctx.image("column_image", column_key(PAGE, 1)).ndim == 2


def test_render_refuses_on_warped_size_mismatch(tmp_path):
    ctx = _ctx(tmp_path)
    out = _run_warp(ctx, ctx.book)
    wins = out["column_windows"]
    rec = wins.columns[0]
    w, h = rec.warped_size
    bad = wins.model_copy(update={"columns": [rec.model_copy(update={"warped_size": (w, h + 30)}), *wins.columns[1:]]})
    ctx.store.write(ctx.book.id, "column_warp", f"p{PAGE:04d}", {"column_windows": bad})
    with pytest.raises(StaleRenderError, match="warped_size"):
        STEPS["column_warp"].render(ctx, "column_image", column_key(PAGE, rec.col))


def test_inner_memo_stamp_follows_products(tmp_path):
    ctx = _ctx(tmp_path)
    _run_warp(ctx, ctx.book)
    stamp = STEPS["cell_shrink"]._inner_memo_stamp
    a = stamp(ctx, PAGE)
    assert a[1] is not None and a[0] is None          # 有 column_windows、没 cells
    m = ctx.store.manifest(ctx.book.id, "column_warp")
    m.put(dataclasses.replace(m.get(f"p{PAGE:04d}"), sha256="другой"))
    assert stamp(ctx, PAGE) != a
