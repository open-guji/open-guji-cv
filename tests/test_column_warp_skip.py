# -*- coding: utf-8 -*-
"""Step2（column_warp）读闸1 page_type_policy 短路 skip 类页——不切列。

2026-09-12 补的行为：闸1判定 skip（封面/书签/空白/牌记）之后，Step2 之前
会照样对这些页跑射影/去噪/清理（纯粹浪费，`page_type.py` 模块头实测书签页
照切会切出 126 个无意义的块）。这里不依赖真实书页数据也不依赖册配置，用合成灰度图 +
自备册与上游产物，只钉「skip 判定 → 空列表」这一条链路。
"""

from __future__ import annotations

import numpy as np

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from helpers import blank_page, make_book, make_borders, make_ctx, make_gate1, skip_gate1
from open_guji_cv.core.step import RunContext, STEPS
from open_guji_cv.products.kinds.border_detect_gate import BorderDetectGateManifest

PAGE = 1
NCOLS = 9


def _ctx(tmp_path, gate_manifest: BorderDetectGateManifest, gray: np.ndarray) -> RunContext:
    """册配置也是测试自备的——只要「版式九列」这一条，不去 load 某本真书
    （那会让这条测试跟着那本书的 yaml 走）。"""
    ctx = make_ctx(tmp_path, make_book(expected_cols=NCOLS), raw={PAGE: gray})
    ctx.store.write(ctx.book.id, "border_detect", f"p{PAGE:04d}",
                    {"borders": make_borders(n_cols=NCOLS)})
    ctx.store.write(ctx.book.id, "border_detect_gate", f"p{PAGE:04d}",
                    {"border_detect_gate_manifest": gate_manifest})
    return ctx


def test_skip_page_produces_no_columns(tmp_path):
    """闸1判 skip（如封面）时，Step2 不切列，产出空 PageWindows。"""
    ctx = _ctx(tmp_path, skip_gate1(PAGE, expected_cols=NCOLS), blank_page())
    step = STEPS["column_warp"]
    out = step.run_page(ctx, PAGE)
    wins = out["column_windows"]
    assert wins.columns == []
    assert wins.page == PAGE


def test_standard_page_still_splits_columns(tmp_path):
    """闸1判 standard（正文）时，Step2 照常按边框切出列——skip 短路不误伤正常页。"""
    ctx = _ctx(tmp_path, make_gate1(PAGE, n_cols=NCOLS, expected_cols=NCOLS),
               blank_page())
    step = STEPS["column_warp"]
    out = step.run_page(ctx, PAGE)
    wins = out["column_windows"]
    assert len(wins.columns) == NCOLS


def test_skip_page_then_column_gate_rejects(tmp_path):
    """端到端：Step2 产出空列表后，闸2（column_gate）直接读闸1 page_type
    拒收，拒因说清楚是「页型判定」而不是「探出列数不对」——2026-09-12
    改动前闸2会自己重新猜一次「只探出 0 列」，这条断言钉死新行为：
    闸2优先读闸1的判定，不再让人看着列数字猜真实原因。

    2026-09-15 补齐：此前这条一直红着——2026-09-12 那轮「闸2/闸3 都直接读闸1」
    只在闸3 落了地，闸2 `column_gate.py` 里没有读 `border_detect_gate_manifest`
    的代码，实跑仍返回 "column_count：只探出 0 列（版式应为 9）"，测试先于实现存在。现在
    闸2 照闸3 的写法查 `ctx.product`，拒因写页型（`page_type_skip`）、不再报列数（`column_gate` 版本
    1.5 → 1.6）。
    （2026-09-13 另有一处 fixture 订正：页型从 blank 换成 cover——blank 已改归
    body 子类，blank+skip 这个组合现在造不出来了。）"""
    ctx = _ctx(tmp_path, skip_gate1(PAGE, expected_cols=NCOLS), blank_page())
    warp_step = STEPS["column_warp"]
    warp_out = warp_step.run_page(ctx, PAGE)
    ctx.store.write(ctx.book.id, "column_warp", f"p{PAGE:04d}", warp_out)

    gate_step = STEPS["column_gate"]
    gate_out = gate_step.run_page(ctx, PAGE)
    gm = gate_out["gate_manifest"]
    assert gm.admitted is False
    assert any(r.startswith("page_type_skip") and "cover" in r for r in gm.reject)
    assert not any("L1" in r for r in gm.reject), (
        "闸1已经说清楚是页型判定，闸2不该再重复猜一次列数原因")
    assert gm.columns == []
