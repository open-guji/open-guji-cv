# -*- coding: utf-8 -*-
"""闸2 的空栏页兜底：页级周期估不出来时用书级 `period_prior` 顶上。

为什么需要（2026-09-13）：栏内没有字就推不出纵向节律，`estimate_shared_period`
必然抛错。但空栏页的界行是齐的、九列切得出来——按用户定的分类层级，
**有界行分九列的就算 body**，blank 只是 body 的一个子类，该正常切、产出
一个「各格皆空」的页，不该整页被拦进异常台账。
vol01 p62/p158/p206 三页就是这么一直挂在异常里的。

守两条，**第二条比第一条要紧**：
1. 估不出来 + 配了先验 → 用先验兜底、页级过闸、写 flag 不写 reject；
2. **能估出来的页一律用当场估的值**——兜底不能改变任何正常页的产物。

不依赖真实书页：合成一张「有界行、栏内无字」的图走真链路。
"""

from __future__ import annotations

import dataclasses

import numpy as np

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext, STEPS
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.kinds.border_detect_gate import BorderDetectGateManifest
from open_guji_cv.products.kinds.borders import Borders, HLineRec, VLineRec
from open_guji_cv.products.store import ProductStore

PAGE = 1
W, H, NCOLS = 900, 1400, 9


def _borders() -> Borders:
    top = HLineRec(y_at_right=40.0, slope=0.0, kind="straight")
    bottom = HLineRec(y_at_right=float(H - 40), slope=0.0, kind="straight")
    xs = np.linspace(60, W - 60, NCOLS + 1)
    return Borders(width=W, height=H, expected_cols=NCOLS, top=top, bottom=bottom,
                   verticals=[VLineRec(x_at_top=float(x), slope=0.0) for x in xs])


def _empty_ruled_page() -> np.ndarray:
    """空栏页：版框 + 九条界行都印着，栏内一个字都没有。"""
    g = np.full((H, W), 255, np.uint8)
    g[40:46, 60:W - 60] = 20                      # 上版框
    g[H - 46:H - 40, 60:W - 60] = 20              # 下版框
    for x in np.linspace(60, W - 60, NCOLS + 1):  # 界行
        g[40:H - 40, int(x) - 2:int(x) + 2] = 20
    return g


def _body_page() -> np.ndarray:
    """正常正文页：同样的栏格，但每栏按固定行距填满字块。"""
    g = _empty_ruled_page()
    xs = np.linspace(60, W - 60, NCOLS + 1)
    for i in range(NCOLS):
        x0, x1 = int(xs[i]) + 6, int(xs[i + 1]) - 6
        for y in range(60, H - 90, 60):           # 行距 60px = 真周期
            g[y:y + 46, x0:x1] = 20
    return g


def _ctx(tmp_path, gray: np.ndarray, period_prior: float | None) -> RunContext:
    store = ProductStore(tmp_path / "products")
    book = load_book("vol01")
    book = dataclasses.replace(book, period_prior=period_prior)
    ctx = RunContext(book, store, ImageCache(tmp_path / "cache"), log=lambda s: None)
    ctx._raw[PAGE] = gray
    store.write(book.id, "border_detect", f"p{PAGE:04d}", {"borders": _borders()})
    store.write(book.id, "border_detect_gate", f"p{PAGE:04d}",
                {"border_detect_gate_manifest": BorderDetectGateManifest(
                    page=PAGE, admitted=True, n_cols=NCOLS, expected_cols=NCOLS,
                    page_type="blank", page_type_policy="standard")})
    return ctx


def _run(ctx) -> tuple:
    warp = STEPS["column_warp"].run_page(ctx, PAGE)
    ctx.store.write(ctx.book.id, "column_warp", f"p{PAGE:04d}", warp)
    return STEPS["column_gate"].run_page(ctx, PAGE)["gate_manifest"]


def test_empty_ruled_page_falls_back_to_book_period(tmp_path):
    """空栏页：用书级先验兜底，页级过闸，写 flag 不写 reject。"""
    gm = _run(_ctx(tmp_path, _empty_ruled_page(), period_prior=115.0))
    assert gm.period == 115.0
    assert gm.period_from_prior is True
    assert gm.admitted is True, "空栏页界行齐全，该过闸正常切"
    assert any("L1f" in f for f in gm.flags)
    assert not any("周期" in r for r in gm.reject), "兜底成功就不该再写 reject"


def test_without_prior_the_page_is_still_rejected(tmp_path):
    """没配 period_prior 的册：行为与加这套机制之前一致（拦下并说明原因）。"""
    gm = _run(_ctx(tmp_path, _empty_ruled_page(), period_prior=None))
    assert gm.period is None
    assert gm.period_from_prior is False
    assert gm.admitted is False
    assert any("周期估不出来" in r for r in gm.reject)
    assert any("period_prior" in r for r in gm.reject), "要提示怎么修，不能只报错"


def test_prior_never_overrides_a_page_that_can_estimate(tmp_path):
    """**最要紧的一条**：能估出来的页一律用当场估的值，兜底不得插手。

    配一个与真实周期差很远的先验（999），正常页的 period 必须仍是估出来的
    那个数、`period_from_prior` 必须是 False——否则等于全书的页级周期被一个
    书级常量悄悄顶替，正常页的产物会跟着变。
    """
    gm = _run(_ctx(tmp_path, _body_page(), period_prior=999.0))
    assert gm.period is not None and gm.period != 999.0, (
        f"正常页不该用先验，实得 period={gm.period}")
    assert gm.period_from_prior is False
