# -*- coding: utf-8 -*-
"""Step1→2 交接闸（补闸1）的判据分层。

核心判断（见 gates/border_detect_gate.py 模块头）：
- L1（block）：探出的列数不等于版式列数——唯一 block 级判据，是这一步补的
  唯一"从零写"的判据，文档说"判据已存在"在现行流水线里是失实的。
- L2/L3（flag，不 block）：界行 w80 跑飞、上/下外框没探到——计算逻辑都
  真实存在（嵌在探测算法内部当筛选用），但没有已验证的"超了就该整页
  作废"的判准，先标出来供人复核，不拦。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext, STEPS
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore

REPO = Path(__file__).resolve().parent.parent


def _run_gate(book: str, page: int):
    """直接跑闸1的 run_page（读现有 borders 产物，不重跑 border_detect）。"""
    store, cache = ProductStore(), ImageCache()
    bk = load_book(book)
    ctx = RunContext(bk, store, cache)
    if not ctx.has_product("borders", page):
        return None
    gate_step = STEPS["border_detect_gate"]
    out = gate_step.run_page(ctx, page)
    return out["border_detect_gate_manifest"]


def test_gate_registered_and_attached_to_border_detect():
    """闸1已挂在 border_detect 出口——补闸1的最基本前提。"""
    assert "border_detect_gate" in STEPS
    gate = STEPS["border_detect"].spec.gate
    assert gate is not None and gate.id == "border_detect_gate"


def test_dev_set_pages_admitted_with_correct_col_count():
    """dev_set 是清楚页/已知难页的分层集，边框探测理应把列数探对——
    这批页本来就是「切分链已验证过」的样本，闸1不该把它们拦下来。"""
    found = False
    for book in ("vol01", "vol02"):
        bk = load_book(book)
        for pg in bk.dev_set:
            m = _run_gate(book, pg)
            if m is None:
                continue
            found = True
            assert m.n_cols == bk.expected_cols, (
                f"{book}/{pg}: 探出 {m.n_cols} 列，版式应为 {bk.expected_cols}——"
                f"dev_set 页不该在这条上出问题：{m.reject}")
            assert m.admitted, f"{book}/{pg} 列数对却未 admitted：{m.reject}"
    if not found:
        pytest.skip("没有可测的 border_detect 产物（先跑一遍管线）")


def test_wrong_col_count_blocks_not_flags():
    """列数不对时必须写进 reject（block），不能只是 flag——这是本闸
    唯一的 block 级判据，跟 L2/L3 的处置方式必须分得开。"""
    for book in ("vol01", "vol02"):
        bk = load_book(book)
        for pg in bk.dev_set:
            m = _run_gate(book, pg)
            if m is None:
                continue
            if m.n_cols != m.expected_cols:
                assert not m.admitted
                assert any("L1" in r for r in m.reject)
                return
    pytest.skip("dev_set 里没有列数不对的页（这是好事，但测不到这条分支）")


def test_missing_outer_border_flags_not_blocks():
    """上/下外框没探到（`top_outer_offset`/`bottom_outer_offset` 为 None）
    只 flag，不影响 admitted——这批书上下外框磨损严重，「没印上」是正常
    情况，不该跟「列数不对」这种整页性问题同等处置。"""
    found = False
    for book in ("vol01", "vol02"):
        bk = load_book(book)
        for pg in bk.dev_set:
            m = _run_gate(book, pg)
            if m is None:
                continue
            if m.top_outer_offset is None or m.bottom_outer_offset is None:
                found = True
                assert m.flags, f"{book}/{pg} 外框缺失但没写 flags"
                if m.n_cols == m.expected_cols:
                    assert m.admitted, (
                        f"{book}/{pg} 列数对、只是外框没探到，不该被 block："
                        f"{m.reject}")
    if not found:
        pytest.skip("dev_set 里没有外框缺失的页")


def test_bend_w80_uses_same_constant_as_detection():
    """闸1的 w80 阈值必须与探测阶段判「单条线跑飞」用的是同一个常量——
    不各写一份阈值（Step0 闸0 的教训：文档说的量和代码实际算的量对不上）。"""
    from open_guji_cv.gates.border_detect_gate import BorderDetectGateParams
    from open_guji_cv.utils.border_geometry import BEND_W80_MAX
    assert BorderDetectGateParams().bend_w80_max_gate == BEND_W80_MAX
