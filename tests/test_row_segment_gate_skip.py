# -*- coding: utf-8 -*-
"""闸3（row_segment_gate）2026-09-12 的两处修复：合成数据，不依赖真实书页。

1. skip 类页直接读闸1 page_type 写清楚的 L0 页级 reject，不看列级 DP 结果。
2. 修复既有漏洞：`columns` 非空但全部被拒时，原先页级 `reject` 留空——
   控制台 ProgressGatePanel 只显示页级 reject，会显示成"p1："后面什么都
   没有，看不出整页为什么没有一列过闸。

2026-09-13 增：L0u「版式未支持」的分桶（职名/目录页从"整页被拦（异常）"里
单列出来）。判据与金标数字在 `clustering/page_type.py`，这里只守分桶逻辑。
"""

from __future__ import annotations

import pytest

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext, STEPS
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.kinds.border_detect_gate import BorderDetectGateManifest
from open_guji_cv.products.kinds.cells import ColumnCells, PageCells
from open_guji_cv.products.store import ProductStore

PAGE = 1


def _ctx(tmp_path, gate_manifest: BorderDetectGateManifest, cells: PageCells | None) -> RunContext:
    store = ProductStore(tmp_path / "products")
    cache = ImageCache(tmp_path / "cache")
    book = load_book("vol01")
    ctx = RunContext(book, store, cache, log=lambda s: None)
    store.write(book.id, "border_detect_gate", f"p{PAGE:04d}",
               {"border_detect_gate_manifest": gate_manifest})
    if cells is not None:
        store.write(book.id, "row_segment", f"p{PAGE:04d}", {"cells": cells})
    return ctx


def test_skip_page_gets_clear_l0_reject_not_dp_symptoms(tmp_path):
    """skip 页即使凑巧有 cells 记录（不该发生，但防御式验证），L0 优先于
    列级判据——不该显示 DP 无解/格数偏离这些下游症状。"""
    gate1 = BorderDetectGateManifest(
        page=PAGE, admitted=False, reject=["L0：页型判定为「cover」，无正文栏格，不套列窗口"],
        n_cols=0, expected_cols=9, page_type="cover", page_type_policy="skip")
    cells = PageCells(page=PAGE, period=None, ref_w=None, columns=[])
    ctx = _ctx(tmp_path, gate1, cells)
    step = STEPS["row_segment_gate"]
    out = step.run_page(ctx, PAGE)["row_segment_gate_manifest"]
    assert out.admitted is False
    assert len(out.reject) == 1
    assert "L0" in out.reject[0] and "cover" in out.reject[0]


def test_standard_page_all_columns_rejected_gets_page_level_summary(tmp_path):
    """非 skip 页、列非空但全部未过：修复前 page_reject 留空，控制台显示
    "p1："后面什么都没有；修复后要给一句页级摘要。

    2026-09-13：这里的拒因**故意不是**「弹性 DP 无解」——那一种现在走 L0u
    「版式未支持」（见 test_all_dp_unsolved_is_unsupported_layout_not_anomaly）。
    本例要守的是「其余原因整页全拒」仍有页级摘要这条老修复。"""
    gate1 = BorderDetectGateManifest(
        page=PAGE, admitted=True, n_cols=9, expected_cols=9,
        page_type="body", page_type_policy="standard")
    cells = PageCells(page=PAGE, period=40.0, ref_w=180.0, columns=[
        ColumnCells(col=1, ok=False, error="页级 period 缺失", n_body_slots=21),
        ColumnCells(col=2, ok=False, error="页级 period 缺失", n_body_slots=21),
    ])
    ctx = _ctx(tmp_path, gate1, cells)
    step = STEPS["row_segment_gate"]
    out = step.run_page(ctx, PAGE)["row_segment_gate_manifest"]
    assert out.admitted is False
    assert out.reject, "全部列被拒时页级 reject 不该留空"
    assert "2" in out.reject[0]
    assert out.unsupported_layout is False, "别的拒因不该被当成版式未支持"


def test_standard_page_some_columns_admitted_has_no_page_reject(tmp_path):
    """至少一列过闸时页级 admitted=True、reject 应为空——不误伤正常情况。"""
    gate1 = BorderDetectGateManifest(
        page=PAGE, admitted=True, n_cols=9, expected_cols=9,
        page_type="body", page_type_policy="standard")
    cells = PageCells(page=PAGE, period=40.0, ref_w=180.0, columns=[
        ColumnCells(col=1, ok=True, n_body_slots=21, boundaries=[0.0] * 22),
    ])
    ctx = _ctx(tmp_path, gate1, cells)
    step = STEPS["row_segment_gate"]
    out = step.run_page(ctx, PAGE)["row_segment_gate_manifest"]
    assert out.admitted is True
    assert out.reject == []


# ── L0u「版式未支持」（2026-09-13）────────────────────────────────
# 判据与金标数字见 clustering/page_type.py 的 UNSUPPORTED_LAYOUT_ERROR 一节。
# 这里守的是分桶逻辑本身：什么该判、什么不该判——**不该判**的几条比该判的
# 更要紧，因为误判的后果是把真故障静默归进"非异常"桶里没人查。

def _body_gate1() -> BorderDetectGateManifest:
    return BorderDetectGateManifest(
        page=PAGE, admitted=True, n_cols=9, expected_cols=9,
        page_type="body", page_type_policy="standard")


def _run(tmp_path, cells: PageCells):
    ctx = _ctx(tmp_path, _body_gate1(), cells)
    return STEPS["row_segment_gate"].run_page(ctx, PAGE)["row_segment_gate_manifest"]


def test_all_dp_unsolved_is_unsupported_layout_not_anomaly(tmp_path):
    """整页各列都是「弹性 DP 无解」→ 判版式未支持，写进产物、页级 reject 带 L0u。"""
    out = _run(tmp_path, PageCells(page=PAGE, period=40.0, ref_w=180.0, columns=[
        ColumnCells(col=i, ok=False, error="弹性 DP 无解", n_body_slots=21)
        for i in range(1, 10)]))
    assert out.admitted is False
    assert out.unsupported_layout is True
    assert out.n_unsupported_columns == 9
    assert out.reject[0].startswith("L0u"), out.reject


def test_partially_solved_page_is_not_unsupported(tmp_path):
    """只要有一列切出来了就不是版式未支持——那页本来就在正常通道里。"""
    out = _run(tmp_path, PageCells(page=PAGE, period=40.0, ref_w=180.0, columns=[
        ColumnCells(col=1, ok=True, n_body_slots=21, boundaries=[0.0] * 22),
        ColumnCells(col=2, ok=False, error="弹性 DP 无解", n_body_slots=21),
    ]))
    assert out.unsupported_layout is False
    assert out.admitted is True


def test_mixed_reject_reasons_stay_anomalous(tmp_path):
    """整页全拒、但拒因**掺了别的来路**（未过交接闸）→ 不判版式未支持。

    这条是红线：真故障会表现成"整页全拒但拒因杂"，必须留在异常里被查，
    不能被静默归进"非异常"桶。（vol01 p62/p158/p206 一度是这个形态——
    空栏页估不出页级周期；那条已由闸2 的 period_prior 兜底根治，见
    test_column_gate_period_prior.py。这里守的是判据本身的严格性。）"""
    out = _run(tmp_path, PageCells(page=PAGE, period=40.0, ref_w=180.0, columns=[
        ColumnCells(col=1, ok=False, error="弹性 DP 无解", n_body_slots=21),
        ColumnCells(col=2, ok=False, error="未过交接闸: 页级未过 L1", n_body_slots=21),
    ]))
    assert out.unsupported_layout is False, "拒因不纯时不该判版式未支持"
    assert not out.reject[0].startswith("L0u")


def test_skip_page_takes_precedence_over_unsupported(tmp_path):
    """闸1 已判 skip 的页：L0 优先，不重复判 L0u——页型只有闸1一个权威来源。"""
    gate1 = BorderDetectGateManifest(
        page=PAGE, admitted=False, reject=["L0：页型判定为「cover」，无正文栏格，不套列窗口"],
        n_cols=9, expected_cols=9, page_type="cover", page_type_policy="skip")
    ctx = _ctx(tmp_path, gate1, PageCells(page=PAGE, period=40.0, ref_w=180.0, columns=[
        ColumnCells(col=i, ok=False, error="弹性 DP 无解", n_body_slots=21)
        for i in range(1, 10)]))
    out = STEPS["row_segment_gate"].run_page(ctx, PAGE)["row_segment_gate_manifest"]
    assert out.unsupported_layout is False
    assert out.reject[0].startswith("L0："), out.reject
