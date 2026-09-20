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

不依赖真实书页、也不依赖册配置：合成一张「有界行、栏内无字」的图 +
自备册走真链路。
"""

from __future__ import annotations

import numpy as np

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from helpers import body_page, make_book, make_borders, make_ctx, make_gate1, ruled_page
from open_guji_cv.core.step import RunContext, STEPS

PAGE = 1
W, H, NCOLS = 900, 1400, 9
PERIOD = 60          # 合成正文页的真行距


def _ctx(tmp_path, gray: np.ndarray, period_prior: float | None) -> RunContext:
    """册配置测试自备：`period_prior` 正是被测的那一项，直接给，不去改某本真书的。"""
    book = make_book(expected_cols=NCOLS, period_prior=period_prior)
    ctx = make_ctx(tmp_path, book, raw={PAGE: gray})
    ctx.store.write(book.id, "border_detect", f"p{PAGE:04d}",
                    {"borders": make_borders(W, H, NCOLS)})
    ctx.store.write(book.id, "border_detect_gate", f"p{PAGE:04d}",
                    {"border_detect_gate_manifest": make_gate1(
                        PAGE, n_cols=NCOLS, expected_cols=NCOLS, page_type="blank")})
    return ctx


def _empty_ruled_page() -> np.ndarray:
    return ruled_page(W, H, NCOLS)


def _body_page() -> np.ndarray:
    return body_page(W, H, NCOLS, period=PERIOD)


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
    # 兜底成功与兜底失败共用判据名 `period_fallback`——判的是同一件事
    # （页级周期估不出来），区别只在处置，而处置由落在 flags 还是 reject
    # 表达，不该靠两个名字（2026-09-18 起判据前缀由层号改成词）。
    assert any(f.startswith("period_fallback") for f in gm.flags)
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

    先验配成真周期 60，正常页的 period 必须是**估出来的** 60（窗口 [42, 84] 含真值），
    且 `period_from_prior` 必须是 False——否则等于全书的页级周期被一个书级常量悄悄
    顶替，正常页的产物会跟着变。

    ⚠️ 这里**不能**拿一个离谱的先验（比如 999）来试：`period_prior` 现在还派生
    自相关窗口（`estimate_shared_period`），999 会把窗口推到 [699, 1398]，估出来的
    就是个 720 的假数——那样即使兜底逻辑坏了这条也会"通过"，测不到它想测的东西。
    先验取真值本身，才能让"估出来的" 和 "先验顶上来的" 在数值上区分不开时，
    仍由 `period_from_prior` 这个标志把两者分开。
    """
    gm = _run(_ctx(tmp_path, _body_page(), period_prior=60.0))
    assert gm.period == 60.0, f"正常页该估出真周期 60，实得 period={gm.period}"
    assert gm.period_from_prior is False, "这一页估得出来，不该走兜底"
