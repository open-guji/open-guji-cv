# -*- coding: utf-8 -*-
"""闸2 L1n 列宽下限（overview#427）：列界切进字里、列图只剩笔画边缘的窄列。

合成页挪一条界行，造出「一列特别窄」；缺省只标记 `column_narrow`，`narrow_reject` 才拒。"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import column_xs, make_book, make_ctx, make_gate1, run_steps, synth_page
from open_guji_cv.gates.column_gate import ColumnGateParams

PAGE = 1


def _gate(tmp_path, shift, **params):
    xs = column_xs(n_cols=9)
    xs[5] += shift                       # 第 5 条界行右挪：左边那列变宽、右边那列变窄
    gray, borders = synth_page(xs=xs)
    book = make_book(expected_cols=borders.expected_cols)
    ctx = make_ctx(tmp_path, book, raw={PAGE: gray})
    if params:
        ctx.params["column_gate"] = ColumnGateParams(**params)
    ctx.store.write(book.id, "border_detect", f"p{PAGE:04d}", {"borders": borders})
    ctx.store.write(book.id, "border_detect_gate", f"p{PAGE:04d}", {"border_detect_gate_manifest": make_gate1(
        PAGE, n_cols=borders.expected_cols, expected_cols=book.expected_cols)})
    return run_steps(ctx, PAGE, ["column_warp", "column_gate"])["gate_manifest"]


def _narrow(gm):
    return {c.col: c for c in gm.columns
            if any(f.startswith("column_narrow") for f in c.flags + c.reject)}


def test_narrow_column_flagged_not_rejected(tmp_path):
    gm = _gate(tmp_path, 40)
    hit = _narrow(gm)
    assert len(hit) == 1, [(c.col, c.band_width) for c in gm.columns]
    (col,) = hit.values()
    assert col.admitted and col.band_width < 0.75 * gm.median_width
    assert all(c.admitted for c in gm.columns)


def test_narrow_reject_switch(tmp_path):
    gm = _gate(tmp_path, 40, narrow_reject=True)
    (col,) = _narrow(gm).values()
    assert not col.admitted and col.reject[0].startswith("column_narrow")
    assert sum(not c.admitted for c in gm.columns) == 1


def test_mildly_narrow_column_not_flagged(tmp_path):
    """偏窄但没到下限（只有 L1c 的 column_width 那条 flag），L1n 不管。"""
    assert not _narrow(_gate(tmp_path, 12))
