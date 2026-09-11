# -*- coding: utf-8 -*-
"""Step3→4 交接闸（补闸3）的判据分层。

核心判断（见 gates/row_segment_gate.py 模块头）：
- L1（block）：DP 无解；n_body_slots 偏离版式格数超过 effective_body_slots
  能正当下调的 1 格。
- L2（flag，不 block）：R2 可改善格线、R2s 真粘连格线——原卡与任务书都明确
  写"flag，不算错，这是图像极限"，`admitted` 不该因为它们变 False。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from open_guji_cv.core.book import load_book
from open_guji_cv.core.spec import page_key
from open_guji_cv.core.step import RunContext, STEPS
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore

REPO = Path(__file__).resolve().parent.parent


def _ws_raw():
    from open_guji_cv.core.workspace import raw_root
    return raw_root()
RAW = _ws_raw() / "data_full" / "zongmu"
needs_raw = pytest.mark.skipif(not RAW.exists(), reason="需要 data_full/zongmu 原图")


def _run_gate(book: str, page: int):
    """直接跑闸3的 run_page（读现有 cells 产物，不重跑 row_segment）。"""
    store, cache = ProductStore(), ImageCache()
    bk = load_book(book)
    ctx = RunContext(bk, store, cache)
    if not ctx.has_product("cells", page):
        return None
    gate_step = STEPS["row_segment_gate"]
    out = gate_step.run_page(ctx, page)
    return out["row_segment_gate_manifest"]


@needs_raw
def test_gate_registered_and_attached_to_row_segment():
    """闸3已挂在 row_segment 出口——补闸3的最基本前提。"""
    assert "row_segment_gate" in STEPS
    gate = STEPS["row_segment"].spec.gate
    assert gate is not None and gate.id == "row_segment_gate"


@needs_raw
def test_dp_unsolved_column_is_blocked():
    """DP 无解（`ok=False`）的列必须 block，不能被 R2/R2s 的 flag 逻辑盖过。"""
    store = ProductStore()
    for book in ("vol01", "vol02"):
        for pg in load_book(book).dev_set:
            m = _run_gate(book, pg)
            if m is None:
                continue
            cells = store.read(book, "row_segment", page_key(pg), "cells")
            unsolved = {c.col for c in cells.columns if not c.ok}
            if not unsolved:
                continue
            for c in m.columns:
                if c.col in unsolved:
                    assert not c.admitted, f"{book}/{pg}c{c.col} DP 无解却被 admitted"
                    assert any("DP 无解" in r for r in c.reject)
            return
    pytest.skip("dev_set 里没有 DP 无解的列")


@needs_raw
def test_effective_body_slots_down_adjustment_is_not_blocked():
    """`effective_body_slots` 正当下调一格（版框装不下 21 格）不该被闸拦——
    这正是任务书黄字警告要求先验证的那条「格数=版式格数」判据的落地方式：
    等于或差 1 都正常，不是「必须严格等于版式格数」。"""
    bk = load_book("vol01")
    m = _run_gate("vol01", 5)
    if m is None:
        pytest.skip("vol01/5 还没跑过 row_segment")
    expected = bk.chars_per_line
    down = [c for c in m.columns if c.n_body_slots == expected - 1]
    if not down:
        pytest.skip("vol01/5 这次产物没有下调一格的列（可能已用不同参数重跑）")
    for c in down:
        assert c.admitted, (
            f"vol01/5c{c.col} n_body_slots={c.n_body_slots}（版式 {expected}，"
            f"下调 1 格是 effective_body_slots 的正当行为）不该被 block："
            f"{c.reject}")


@needs_raw
def test_r2_and_r2s_flag_but_do_not_block():
    """R2（可改善）/ R2s（真粘连）格线存在时只 flag，`admitted` 仍为 True——
    原卡与任务书明确写"flag，不算错，这是图像极限"。"""
    found = False
    for book in ("vol01", "vol02"):
        for pg in load_book(book).dev_set:
            m = _run_gate(book, pg)
            if m is None:
                continue
            for c in m.columns:
                if (c.n_r2 or c.n_r2s) and c.admitted:
                    found = True
                    assert c.flags, f"{book}/{pg}c{c.col} 有 R2/R2s 但没写 flags"
    if not found:
        pytest.skip("dev_set 里没有 R2/R2s 命中的、仍被 admitted 的列")


@needs_raw
def test_rulers_classify_boundary_matches_gate_counts():
    """闸3自己数的 n_r2/n_r2s/n_r2x 必须与 `eval.rulers.measure()` 用同一个
    `classify_boundary` 函数——这里只验证两处调用的是同一个函数对象，
    不是各写一份判据（Step0 闸 0 的教训）。"""
    from open_guji_cv.eval import rulers
    from open_guji_cv.gates import row_segment_gate
    assert row_segment_gate.classify_boundary is rulers.classify_boundary


@needs_raw
def test_page_admitted_iff_any_column_admitted():
    """页级 admitted 是"至少一列能过"的语义——不是所有列都过。闸2的页级判据
    是几何整页性问题；闸3没有页级判据，页级只是列级的聚合视图。"""
    for book in ("vol01", "vol02"):
        for pg in load_book(book).dev_set:
            m = _run_gate(book, pg)
            if m is None or not m.columns:
                continue
            assert m.admitted == any(c.admitted for c in m.columns)
            return
    pytest.skip("dev_set 里没有可测的页")
