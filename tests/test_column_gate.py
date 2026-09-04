# -*- coding: utf-8 -*-
"""Step2→3 交接闸的判据分层。

守住 2026-09-03 的那次改动：**列宽偏离是列级判据，不是页级**。
它逐列算得出，却曾被放在页级拒因里 —— 一列坏就整页 9 列作废。
实证见 doc/step3_error_survey.md 乙类（vol01/42 八列完好只因 c9 坏而全废）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from open_guji_cv.core.book import load_book
from open_guji_cv.core.engine import Engine
from open_guji_cv.core.pipeline import load_pipeline
from open_guji_cv.core.spec import page_key
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data_full" / "zongmu"
needs_raw = pytest.mark.skipif(not RAW.exists(), reason="需要 data_full/zongmu 原图")


def _gate(book: str, page: int):
    """跑到闸为止，返回 gate_manifest（用真实产物缓存，不重算上游）。"""
    store = ProductStore()
    g = store.read(book, "column_gate", page_key(page), "gate_manifest")
    if g is None:
        pytest.skip(f"{book}/{page} 还没跑过闸")
    return g


@needs_raw
def test_wide_column_blocks_only_itself_not_whole_page():
    """vol01/42：只有 c9 圈进了界行，c1~c8 必须照常放行。"""
    g = _gate("vol01", 42)
    assert g.admitted, "页级不该因单列宽度而拒绝"
    blocked = [c.col for c in g.columns if not c.admitted]
    assert blocked == [9], f"应只拦 c9，实际拦了 {blocked}"
    c9 = next(c for c in g.columns if c.col == 9)
    assert any("L1c" in r for r in c9.reject)
    # 其余八列必须都能用
    assert sum(1 for c in g.columns if c.admitted) == 8


@needs_raw
def test_page_priors_survive_dropping_wide_column():
    """页级 period / ref_w 由几何正常的列算出，异常列被剔除后仍在健康区间。"""
    for book, page in [("vol01", 42), ("vol02", 3), ("vol02", 119)]:
        g = _gate(book, page)
        if not g.admitted:
            continue
        assert g.period is not None and 100 <= g.period <= 125, \
            f"{book}/{page} period={g.period} 落在正文页健康区间外"
        assert g.ref_w is not None and 140 <= g.ref_w <= 210


@needs_raw
def test_page_level_still_rejects_wrong_column_count():
    """列数不对仍是页级问题——整页的列编号和窗口一起错位，单列救不回来。"""
    store = ProductStore()
    found = False
    for pg in load_book("vol02").all_pages():
        d = store.read_raw("vol02", "column_gate", page_key(pg))
        if not d:
            continue
        gm = d["gate_manifest"]
        if not gm["admitted"] and any("只探出" in r for r in gm["reject"]):
            found = True
            assert all(not c["admitted"] for c in gm["columns"]), \
                "列数不对时整页都该拒绝"
            break
    if not found:
        pytest.skip("本册没有列数不对的页")


@needs_raw
def test_width_reject_never_appears_at_page_level():
    """列宽偏离只能出现在列级 reject 里，页级拒因不许再有它。

    查行为而不是查源码文本——注释里提到「列宽」是正常的。
    """
    store = ProductStore()
    checked = 0
    for book in ("vol01", "vol02"):
        for pg in load_book(book).all_pages():
            d = store.read_raw(book, "column_gate", page_key(pg))
            if not d:
                continue
            gm = d["gate_manifest"]
            checked += 1
            for r in gm["reject"]:
                assert "列宽" not in r, f"{book}/{pg} 页级拒因里还有列宽：{r}"
    if not checked:
        pytest.skip("还没有闸产物")
