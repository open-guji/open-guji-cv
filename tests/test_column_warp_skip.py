# -*- coding: utf-8 -*-
"""Step2（column_warp）读闸1 page_type_policy 短路 skip 类页——不切列。

2026-09-12 补的行为：闸1判定 skip（封面/书签/空白/牌记）之后，Step2 之前
会照样对这些页跑射影/去噪/清理（纯粹浪费，`page_type.py` 模块头实测书签页
照切会切出 126 个无意义的块）。这里不依赖真实书页数据，用合成灰度图 +
monkeypatch 隔离上游产物，只钉「skip 判定 → 空列表」这一条链路。
"""

from __future__ import annotations

import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext, STEPS
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.kinds.border_detect_gate import BorderDetectGateManifest
from open_guji_cv.products.kinds.borders import Borders, HLineRec, VLineRec
from open_guji_cv.products.store import ProductStore

PAGE = 1


def _borders(w: int = 900, h: int = 1400, n_cols: int = 9) -> Borders:
    top = HLineRec(y_at_right=40.0, slope=0.0, kind="straight")
    bottom = HLineRec(y_at_right=float(h - 40), slope=0.0, kind="straight")
    xs = np.linspace(60, w - 60, n_cols + 1)
    verticals = [VLineRec(x_at_top=float(x), slope=0.0) for x in xs]
    return Borders(width=w, height=h, expected_cols=n_cols, top=top, bottom=bottom,
                   verticals=verticals)


def _ctx(tmp_path, gate_manifest: BorderDetectGateManifest, gray: np.ndarray) -> RunContext:
    store = ProductStore(tmp_path / "products")
    cache = ImageCache(tmp_path / "cache")
    book = load_book("vol01")
    ctx = RunContext(book, store, cache, log=lambda s: None)
    ctx._raw[PAGE] = gray  # 绕开真实原图文件，直接注入合成图（raw_page 有缓存）
    store.write(book.id, "border_detect", f"p{PAGE:04d}", {"borders": _borders()})
    store.write(book.id, "border_detect_gate", f"p{PAGE:04d}",
               {"border_detect_gate_manifest": gate_manifest})
    return ctx


def test_skip_page_produces_no_columns(tmp_path):
    """闸1判 skip（如封面）时，Step2 不切列，产出空 PageWindows。"""
    gray = np.full((1400, 900), 255, dtype=np.uint8)
    gate = BorderDetectGateManifest(
        page=PAGE, admitted=False, reject=["L0：页型判定为「cover」，无正文栏格，不套列窗口"],
        n_cols=0, expected_cols=9, page_type="cover", page_type_policy="skip")
    ctx = _ctx(tmp_path, gate, gray)
    step = STEPS["column_warp"]
    out = step.run_page(ctx, PAGE)
    wins = out["column_windows"]
    assert wins.columns == []
    assert wins.page == PAGE


def test_standard_page_still_splits_columns(tmp_path):
    """闸1判 standard（正文）时，Step2 照常按边框切出列——skip 短路不误伤正常页。"""
    gray = np.full((1400, 900), 255, dtype=np.uint8)
    gate = BorderDetectGateManifest(
        page=PAGE, admitted=True, n_cols=9, expected_cols=9,
        page_type="body", page_type_policy="standard")
    ctx = _ctx(tmp_path, gate, gray)
    step = STEPS["column_warp"]
    out = step.run_page(ctx, PAGE)
    wins = out["column_windows"]
    assert len(wins.columns) == 9


def test_skip_page_then_column_gate_rejects(tmp_path):
    """端到端：Step2 产出空列表后，闸2（column_gate）直接读闸1 page_type
    拒收，拒因说清楚是「页型判定」而不是「探出列数不对」——2026-09-12
    改动前闸2会自己重新猜一次 L1（"只探出 0 列"），这条断言钉死新行为：
    闸2优先读闸1的判定，不再让人看着列数字猜真实原因。

    2026-09-15 补齐：此前这条一直红着——2026-09-12 那轮「闸2/闸3 都直接读闸1」
    只在闸3 落了地，闸2 `column_gate.py` 里没有读 `border_detect_gate_manifest`
    的代码，实跑仍返回 "L1：只探出 0 列（版式应为 9）"，测试先于实现存在。现在
    闸2 照闸3 的写法查 `ctx.product`，L0 写页型、不再报列数（`column_gate` 版本
    1.5 → 1.6）。
    （2026-09-13 另有一处 fixture 订正：页型从 blank 换成 cover——blank 已改归
    body 子类，blank+skip 这个组合现在造不出来了。）"""
    gray = np.full((1400, 900), 255, dtype=np.uint8)
    gate1 = BorderDetectGateManifest(
        page=PAGE, admitted=False, reject=["L0：页型判定为「cover」，无正文栏格，不套列窗口"],
        n_cols=0, expected_cols=9, page_type="cover", page_type_policy="skip")
    ctx = _ctx(tmp_path, gate1, gray)
    warp_step = STEPS["column_warp"]
    warp_out = warp_step.run_page(ctx, PAGE)
    ctx.store.write(ctx.book.id, "column_warp", f"p{PAGE:04d}", warp_out)

    gate_step = STEPS["column_gate"]
    gate_out = gate_step.run_page(ctx, PAGE)
    gm = gate_out["gate_manifest"]
    assert gm.admitted is False
    assert any("L0" in r and "cover" in r for r in gm.reject)
    assert not any("L1" in r for r in gm.reject), (
        "闸1已经说清楚是页型判定，闸2不该再重复猜一次列数原因")
    assert gm.columns == []
