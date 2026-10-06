# -*- coding: utf-8 -*-
"""职名页分支（overview#450，S4）：`utils/roster_segment` + `row_segment.roster_pages` +
闸3 豁免 + Step4 逐框裁。合成数据，不读任何真书。

合成字照 cv-debug-method §七：**用笔画画，不画实心块**——几条 5～8px 的横竖笔，
上下结构的字（思、吉）中间留白，这样「并碎块」那一步才真被测到。
"""

from __future__ import annotations

import numpy as np

import open_guji_cv.steps  # noqa: F401  —— 注册 Step / 产物种类
from helpers import make_book, run_keben_chain
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.kinds.cells import CellRec, ColumnCells, PageCells
from open_guji_cv.utils.roster_segment import (prepare, segment_roster_column,
                                               segment_roster_page)

W = 180          # 列图宽
EM = 110         # 大字字身


def _glyph(img, y, x, size, *, split=False, stroke=7):
    """在 (y, x) 画一个 size×size 的笔画字：外框两竖 + 三横；split=True 时上下两半中间留白。"""
    s = size
    if split:                                   # 上下结构：上半「十」、下半「口」，中间 12% 留白
        h1 = int(0.44 * s)
        img[y:y + stroke, x:x + s] = 0
        img[y:y + h1, x + s // 2 - stroke // 2:x + s // 2 + stroke // 2 + 1] = 0
        y2 = y + int(0.56 * s)
        img[y2:y + s, x:x + stroke] = 0
        img[y2:y + s, x + s - stroke:x + s] = 0
        img[y2:y2 + stroke, x:x + s] = 0
        img[y + s - stroke:y + s, x:x + s] = 0
        return
    img[y:y + s, x:x + stroke] = 0
    img[y:y + s, x + s - stroke:x + s] = 0
    for t in (0, s // 2, s - stroke):
        img[y + t:y + t + stroke, x:x + s] = 0


def _column(h=2400):
    return np.full((h, W), 255, np.uint8)


def _roster_column():
    """官衔 4 字匀开（第 3 字上下结构）+ 偏右小「臣」+ 两字人名贴底。返回 (图, 读序里每字的 y)。"""
    g = _column()
    ys = [100, 560, 1020, 1480]
    for i, y in enumerate(ys):
        _glyph(g, y, 35, EM, split=(i == 2))
    _glyph(g, 1610, 110, 50, stroke=5)          # 臣：小、偏右、紧贴官衔末字下方
    _glyph(g, 1700, 35, EM)
    _glyph(g, 2150, 35, EM)
    return g, ys + [1610, 1700, 2150]


def _seg_one(g):
    ink, width = prepare(g, (10.0, W - 10.0))
    return segment_roster_column(ink, EM)


def test_spread_title_small_chen_and_name_counted_one_per_glyph():
    g, ys = _roster_column()
    rc = _seg_one(g)
    assert [it.kind for it in rc.items] == ["char"] * 7
    assert [it.y0 for it in rc.items] == ys                 # 读序 = 自上而下，上下结构字没被拆成两个
    chen = rc.items[4]
    assert chen.x0 > W / 2 and chen.x1 - chen.x0 < EM / 2   # 「臣」偏右的小框
    assert "roster_dense_guess" not in rc.flags


def test_double_line_small_text_reads_right_line_then_left_line():
    g = _column()
    _glyph(g, 100, 35, EM)                                  # 一个大字起头
    for k in range(4):                                      # 雙行：右行 4 字、左行 3 字，相位错开半字
        _glyph(g, 300 + k * 60, 100, 50, stroke=5)
    for k in range(3):
        _glyph(g, 330 + k * 60, 25, 50, stroke=5)
    _glyph(g, 700, 35, EM)
    rc = _seg_one(g)
    kinds = [it.kind for it in rc.items]
    assert kinds == ["char"] + ["jiazhu_a"] * 4 + ["jiazhu_b"] * 3 + ["char"]
    a = [it for it in rc.items if it.kind == "jiazhu_a"]
    b = [it for it in rc.items if it.kind == "jiazhu_b"]
    assert all(it.x0 > W / 2 - 10 for it in a) and all(it.x1 < W / 2 + 10 for it in b)
    assert [it.y0 for it in a] == sorted(it.y0 for it in a)


def test_compressed_run_keeps_flat_glyphs_apart():
    """压扁密排：8 个扁字（高 ≈ 0.55 宽）各隔 4px——不许两两并成「方字」。"""
    g = _column()
    y = 100
    for _ in range(8):
        g[y:y + 6, 35:145] = 0                              # 扁字：两横一竖
        g[y + 54:y + 60, 35:145] = 0
        g[y:y + 60, 87:94] = 0
        y += 64
    rc = _seg_one(g)
    assert len(rc.items) == 8


def test_touching_glyphs_are_split_and_flagged_as_guess():
    g = _column()
    _glyph(g, 100, 35, EM)
    _glyph(g, 100 + EM, 35, EM)                              # 两个大字物理粘连，没有墨谷
    rc = _seg_one(g)
    assert len(rc.items) == 2
    assert "roster_dense_guess" in rc.flags


def test_page_level_em_from_isolated_big_glyphs():
    g, _ = _roster_column()
    out = segment_roster_page([(g, (10.0, W - 10.0)), (g.copy(), (10.0, W - 10.0))])
    assert len(out) == 2 and all(len(rc.items) == 7 for rc in out)
    assert abs(out[0].em - EM) < 0.1 * EM


# ── Step3 分支 / 闸3 / Step4 ──────────────────────────────────────────────

def _chain(tmp_path, monkeypatch, roster: bool, through: str):
    params = {"row_segment": {"roster_pages": ["1"]}} if roster else {}
    book = make_book(expected_cols=4, chars_per_line=21, params=params)
    # synth_page 的 col_n_chars 按界行 x 从左往右数；Step2 起列号从右往左（1 = 最右）
    return run_keben_chain(tmp_path, monkeypatch, book=book, through=through, h=2000,
                           n_cols=4, w=500, period=100, col_n_chars={4: 3, 3: 7, 2: 12, 1: 5})


def test_roster_branch_off_by_default_keeps_fixed_slot_dp(tmp_path, monkeypatch):
    _, out = _chain(tmp_path, monkeypatch, roster=False, through="row_segment")
    assert all("roster" not in cc.flags for cc in out["cells"].columns)
    assert {cc.n_body_slots for cc in out["cells"].columns if cc.ok} <= {20, 21}


def test_roster_branch_counts_actual_glyphs_and_gate_does_not_reject(tmp_path, monkeypatch):
    _, out = _chain(tmp_path, monkeypatch, roster=True, through="row_segment_gate")
    cols = {cc.col: cc for cc in out["cells"].columns}
    assert {c: cc.n_body_slots for c, cc in cols.items()} == {1: 3, 2: 7, 3: 12, 4: 5}  # 合成块无墨谷之外的结构，一块一字
    assert all(cc.ok and "roster" in cc.flags and cc.boundaries == [] for cc in cols.values())
    assert all([c.pos for c in cc.cells] == list(range(1, cc.n_body_slots + 1))
               for cc in cols.values())
    gm = out["row_segment_gate_manifest"]
    assert gm.admitted and all(c.admitted and not c.reject for c in gm.columns)


def test_roster_cells_are_cropped_by_their_own_box_in_step4(tmp_path, monkeypatch):
    _, out = _chain(tmp_path, monkeypatch, roster=True, through="cell_shrink")
    cells = {cc.col: cc for cc in out["cells"].columns}
    for col in out["char_index"].columns:
        cc = cells[col.col]
        assert col.n_instances == cc.n_body_slots
        for ch, cell in zip(sorted(col.chars, key=lambda c: c.pos), sorted(cc.cells, key=lambda c: c.pos)):
            x0, y0, x1, y1 = ch.bbox_col
            assert x0 <= cell.x0 and x1 >= cell.x1 and y0 <= cell.y0 and y1 >= cell.y1
            assert (y1 - y0) < 1.5 * (cell.y1 - cell.y0) + 10   # 没被扩成满格/邻字
            assert ch.patch_key and "lost_patch" not in ch.flags


def test_gate_flags_dense_guess_and_skips_slot_count_for_roster_columns(tmp_path):
    from helpers import make_ctx, make_gate1
    ctx = make_ctx(tmp_path, make_book(expected_cols=2))
    ctx.store.write(ctx.book.id, "border_detect_gate", "p0001",
                    {"border_detect_gate_manifest": make_gate1(1, n_cols=2, expected_cols=2)})
    cell = CellRec(slot=1, pos=1, y0=0, y1=50, x0=0, x1=50, kind="char", order=0)
    cells = PageCells(page=1, period=60.0, ref_w=100.0, columns=[
        ColumnCells(col=1, ok=True, n_body_slots=1, cells=[cell], flags=["roster"]),
        ColumnCells(col=2, ok=True, n_body_slots=1, cells=[cell],
                    flags=["roster", "roster_dense_guess"]),
    ])
    ctx.store.write(ctx.book.id, "row_segment", "p0001", {"cells": cells})
    gm = STEPS["row_segment_gate"].run_page(ctx, 1)["row_segment_gate_manifest"]
    assert all(c.admitted for c in gm.columns)
    assert not gm.columns[0].flags
    assert any(f.startswith("roster_dense_guess") for f in gm.columns[1].flags)
