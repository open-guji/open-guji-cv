# -*- coding: utf-8 -*-
"""Step3→4 交接闸（补闸3）的判据分层。

核心判断（见 gates/row_segment_gate.py 模块头）：
- L1（block）：DP 无解；n_body_slots 偏离版式格数超过 effective_body_slots
  能正当下调的 1 格。
- L2（flag，不 block）：R2 可改善格线、R2s 真粘连格线——原卡与任务书都明确
  写"flag，不算错，这是图像极限"，`admitted` 不该因为它们变 False。

2026-09-20 重写：原先六条全是「扫 dev_set 产物、找到符合形态的就断言、找不到
就 skip」，工作区不在就一条都跑不了。现在每条自己合成出要测的形态——
`helpers.synth_page` 造版式，跑真的 Step2/Step3 链路，要造穿墨就把切出来的
格线挪几个像素。三种穿墨形态的合成参数实测标定过（见各用例）：

| 形态 | 怎么造 | 判据说什么 |
|---|---|---|
| 干净 | 格线落在字块之间的白缝上 | 不计数 |
| R2 可改善 | 格线挪 10px（±12px 内仍有净谷）| flag |
| R2s 真粘连 | 字块之间不留白（`gap=0`）| flag，图像极限 |
"""

from __future__ import annotations

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from helpers import make_book, make_ctx, make_gate1, run_steps, synth_page
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.kinds.cells import ColumnCells, PageCells

PAGE = 1
NCOLS, NCHARS, PERIOD = 9, 10, 120


def _chain(tmp_path, monkeypatch, *, gap: int = 14, through: str = "row_segment"):
    """合成一页 → 跑到指定步骤，返回 (ctx, 产物字典)。

    闸3 取列投影走的是 `eval/rulers._col_profile`，它**自己 new 一个
    `ImageCache()`**、不认 ctx 的缓存根，所以这里必须把 `GUJI_CACHE_DIR`
    一起指过去（`make_ctx(monkeypatch=...)` 负责），否则列图一张都读不到、
    R2/R2s 静默恒为 0——测试照样绿，但什么都没量到。
    """
    gray, borders = synth_page(period=PERIOD, n_chars=NCHARS, n_cols=NCOLS, gap=gap)
    ctx = make_ctx(tmp_path, make_book(expected_cols=NCOLS, chars_per_line=NCHARS),
                   raw={PAGE: gray}, monkeypatch=monkeypatch)
    ctx.store.write(ctx.book.id, "border_detect", f"p{PAGE:04d}", {"borders": borders})
    ctx.store.write(ctx.book.id, "border_detect_gate", f"p{PAGE:04d}",
                    {"border_detect_gate_manifest": make_gate1(
                        PAGE, n_cols=NCOLS, expected_cols=NCOLS)})
    steps = ["column_warp", "column_gate", "row_segment", "row_segment_gate"]
    return ctx, run_steps(ctx, PAGE, steps[:steps.index(through) + 1])


def _regate(ctx, cells: PageCells):
    """换一份 cells 重跑闸3（列图仍是上一步真切出来的那张）。"""
    ctx.store.write(ctx.book.id, "row_segment", f"p{PAGE:04d}", {"cells": cells})
    return STEPS["row_segment_gate"].run_page(ctx, PAGE)["row_segment_gate_manifest"]


def test_gate_registered_and_attached_to_row_segment():
    """闸3已挂在 row_segment 出口——补闸3的最基本前提。"""
    assert "row_segment_gate" in STEPS
    gate = STEPS["row_segment"].spec.gate
    assert gate is not None and gate.id == "row_segment_gate"


def test_clean_cuts_are_admitted_without_flags(tmp_path, monkeypatch):
    """格线落在字缝上的正常列：过闸，且不该凭空挂 R2/R2s。

    这条是下面几条的**基线**——没有它，「挪了格线就 flag」可能只是判据
    对什么都 flag。
    """
    _, out = _chain(tmp_path, monkeypatch, through="row_segment_gate")
    m = out["row_segment_gate_manifest"]
    assert m.admitted, m.reject
    assert all(c.admitted for c in m.columns), [c.reject for c in m.columns]
    assert all(c.n_r2 == 0 and c.n_r2s == 0 for c in m.columns), \
        [(c.col, c.n_r2, c.n_r2s) for c in m.columns]


def test_dp_unsolved_column_is_blocked(tmp_path, monkeypatch):
    """DP 无解（`ok=False`）的列必须 block，不能被 R2/R2s 的 flag 逻辑盖过。"""
    ctx, out = _chain(tmp_path, monkeypatch)
    cells: PageCells = out["cells"]
    broken = cells.columns[0].model_copy(update={"ok": False, "error": "弹性 DP 无解"})
    m = _regate(ctx, cells.model_copy(update={"columns": [broken] + list(cells.columns[1:])}))
    bad = next(c for c in m.columns if c.col == broken.col)
    assert not bad.admitted, "DP 无解却被 admitted"
    assert any(r.startswith("dp_no_solution") for r in bad.reject), bad.reject
    assert all(c.admitted for c in m.columns if c.col != broken.col), "不该连累别的列"


def test_effective_body_slots_down_adjustment_is_not_blocked(tmp_path, monkeypatch):
    """`effective_body_slots` 正当下调一格（版框装不下 21 格）不该被闸拦——
    这正是任务书黄字警告要求先验证的那条「格数=版式格数」判据的落地方式：
    等于或差 1 都正常，不是「必须严格等于版式格数」。"""
    ctx, out = _chain(tmp_path, monkeypatch)
    cells: PageCells = out["cells"]
    down = cells.columns[0].model_copy(update={"n_body_slots": NCHARS - 1})
    m = _regate(ctx, cells.model_copy(update={"columns": [down]}))
    assert m.columns[0].admitted, (
        f"n_body_slots={NCHARS - 1}（版式 {NCHARS}，下调 1 格是 effective_body_slots "
        f"的正当行为）不该被 block：{m.columns[0].reject}")


def test_slot_count_beyond_one_is_blocked(tmp_path, monkeypatch):
    """差 2 格就不是正当下调了——容许的是 `slot_tol`，不是「随便几格都行」。"""
    ctx, out = _chain(tmp_path, monkeypatch)
    cells: PageCells = out["cells"]
    off = cells.columns[0].model_copy(update={"n_body_slots": NCHARS - 3})
    m = _regate(ctx, cells.model_copy(update={"columns": [off]}))
    assert not m.columns[0].admitted
    assert any(r.startswith("slot_count") for r in m.columns[0].reject), m.columns[0].reject


def test_improvable_cuts_flag_but_do_not_block(tmp_path, monkeypatch):
    """R2（可改善）格线只 flag，`admitted` 仍为 True——原卡与任务书明确写
    "flag，不算错，这是图像极限"。

    合成：把真切出来的格线整体挪 10px。挪这么点还落在原字缝的 ±12px 窗口里，
    所以判为「可改善」（净谷就在旁边）而不是「真粘连」。
    """
    ctx, out = _chain(tmp_path, monkeypatch)
    cells: PageCells = out["cells"]
    c0 = cells.columns[0]
    moved = c0.model_copy(update={"boundaries": [b + 10 for b in c0.boundaries]})
    m = _regate(ctx, cells.model_copy(update={"columns": [moved]}))
    col = m.columns[0]
    assert col.n_r2 > 0, f"挪偏了格线却没数出 R2：r2={col.n_r2} r2x={col.n_r2x} r2s={col.n_r2s}"
    assert col.admitted, f"R2 是 flag 不是 block：{col.reject}"
    assert any(f.startswith("cut_improvable") for f in col.flags), col.flags


def test_touching_cuts_flag_but_do_not_block(tmp_path, monkeypatch):
    """R2s（真粘连）同样只 flag——上下字在扫描上物理相连，任何墨谷判据都
    找不到零墨行，拦下来等于永久卡死。

    合成：`gap=0` 的页，字块之间一行白都不留，整列找不到谷。
    """
    ctx, out = _chain(tmp_path, monkeypatch, gap=0, through="column_gate")
    h = out["column_windows"].columns[0].warped_size[1]
    step = (h - 40) / NCHARS
    cc = ColumnCells(col=1, ok=True, period=float(PERIOD), n_body_slots=NCHARS,
                     boundaries=[20.0 + i * step for i in range(NCHARS + 1)], cells=[])
    col = _regate(ctx, PageCells(page=PAGE, period=float(PERIOD), ref_w=80.0,
                                 columns=[cc])).columns[0]
    assert col.n_r2s > 0, f"整列没有墨谷却没数出 R2s：r2s={col.n_r2s}"
    assert col.admitted, f"R2s 是 flag 不是 block：{col.reject}"
    assert any(f.startswith("cut_touching") for f in col.flags), col.flags


def test_rulers_classify_boundary_matches_gate_counts():
    """闸3自己数的 n_r2/n_r2s/n_r2x 必须与 `eval.rulers.measure()` 用同一个
    `classify_boundary` 函数——这里只验证两处调用的是同一个函数对象，
    不是各写一份判据（Step0 闸 0 的教训）。"""
    from open_guji_cv.eval import rulers
    from open_guji_cv.gates import row_segment_gate
    assert row_segment_gate.classify_boundary is rulers.classify_boundary


def test_page_admitted_iff_any_column_admitted(tmp_path, monkeypatch):
    """页级 admitted 是"至少一列能过"的语义——不是所有列都过。闸2的页级判据
    是几何整页性问题；闸3没有页级判据，页级只是列级的聚合视图。"""
    ctx, out = _chain(tmp_path, monkeypatch)
    cells: PageCells = out["cells"]

    # 全好 → 过
    m = _regate(ctx, cells)
    assert m.admitted is True and all(c.admitted for c in m.columns)

    # 一列坏 → 仍过（还有别的列能用）
    broken = cells.columns[0].model_copy(update={"ok": False, "error": "弹性 DP 无解"})
    mixed = cells.model_copy(update={"columns": [broken] + list(cells.columns[1:])})
    m = _regate(ctx, mixed)
    assert m.admitted is True == any(c.admitted for c in m.columns)

    # 全坏 → 不过
    all_bad = cells.model_copy(update={"columns": [
        c.model_copy(update={"ok": False, "error": "弹性 DP 无解"}) for c in cells.columns]})
    m = _regate(ctx, all_bad)
    assert m.admitted is False and not any(c.admitted for c in m.columns)
