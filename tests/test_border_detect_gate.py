# -*- coding: utf-8 -*-
"""Step1→2 交接闸（补闸1）的判据分层。

核心判断（见 gates/border_detect_gate.py 模块头）：
- L1（block）：探出的列数不等于版式列数——唯一 block 级判据，是这一步补的
  唯一"从零写"的判据，文档说"判据已存在"在现行流水线里是失实的。
- L2/L3（flag，不 block）：界行 w80 跑飞、上/下外框没探到——计算逻辑都
  真实存在（嵌在探测算法内部当筛选用），但没有已验证的"超了就该整页
  作废"的判准，先标出来供人复核，不拦。

2026-09-20 重写：原先三条用例是**扫工作区里碰巧有的 border_detect 产物**，
再在里头找「列数不对的页」「外框缺失的页」来断言——没有就 `skip`。两个毛病：

1. 跑批一变测试就跟着变（找不到样本就静默跳过，云端一条都测不到）；
2. 真正想钉的是**判据分层**（谁 block、谁只 flag），那跟「这次跑批碰上了
   什么页」根本无关。其中一条还因此常年没执行过，断言写的是 `"L1" in reject`
   ——闸子里的拒因前缀早就是 `column_count`，这条要是真跑过当场就红了。

现在每条用例自己造出要测的那一种 `Borders`，判据分层直接可测。
"""

from __future__ import annotations

import pytest

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from helpers import body_page, make_book, make_borders, make_ctx
from open_guji_cv.core.step import STEPS

PAGE = 1
NCOLS = 9


def _run_gate(tmp_path, borders, *, expected_cols: int = NCOLS, gray=None):
    """把给定的 `Borders` 摆成 Step1 产物，跑闸1，返回 manifest。"""
    gray = body_page(n_cols=NCOLS) if gray is None else gray
    ctx = make_ctx(tmp_path, make_book(expected_cols=expected_cols),
                   raw={PAGE: gray})
    ctx.store.write(ctx.book.id, "border_detect", f"p{PAGE:04d}", {"borders": borders})
    return STEPS["border_detect_gate"].run_page(ctx, PAGE)["border_detect_gate_manifest"]


def test_gate_registered_and_attached_to_border_detect():
    """闸1已挂在 border_detect 出口——补闸1的最基本前提。"""
    assert "border_detect_gate" in STEPS
    gate = STEPS["border_detect"].spec.gate
    assert gate is not None and gate.id == "border_detect_gate"


def test_correct_col_count_is_admitted(tmp_path):
    """列数与版式一致的正文页照常过闸——闸1不该拦正常页。"""
    m = _run_gate(tmp_path, make_borders(n_cols=NCOLS))
    assert m.n_cols == NCOLS == m.expected_cols
    assert m.admitted, m.reject
    assert m.reject == []


@pytest.mark.parametrize("detected", [7, 8, 10, 12])
def test_wrong_col_count_blocks_not_flags(tmp_path, detected):
    """列数不对时必须写进 reject（block），不能只是 flag——这是本闸
    唯一的 block 级判据，跟 L2/L3 的处置方式必须分得开。

    多探、少探都测：少探常见于界行磨没，多探常见于把笔画认成线，
    两边都该 block。"""
    m = _run_gate(tmp_path, make_borders(n_cols=detected), expected_cols=NCOLS)
    assert m.n_cols == detected
    assert not m.admitted
    assert any(r.startswith("column_count") for r in m.reject), m.reject
    # 判据名进 reject 就说明是 block 级；flags 里不该出现同一条
    assert not any(f.startswith("column_count") for f in m.flags)


def test_missing_outer_border_flags_not_blocks(tmp_path):
    """上/下外框没探到（`top_outer_offset`/`bottom_outer_offset` 为 None）
    只 flag，不影响 admitted——这批书上下外框磨损严重，「没印上」是正常
    情况，不该跟「列数不对」这种整页性问题同等处置。"""
    b = make_borders(n_cols=NCOLS)
    assert b.top_outer_offset is None and b.bottom_outer_offset is None
    m = _run_gate(tmp_path, b)
    assert m.admitted, f"外框没探到不该 block：{m.reject}"
    assert any(f.startswith("outer_frame_missing") for f in m.flags), m.flags


def test_single_frame_side_is_not_reported_missing(tmp_path):
    """單邊框的那一边本来就没有第二条线，`outer` 为 None 是对的，不该 flag
    ——否则整册單邊框的书每页都挂一条假 flag，真问题就被淹了。"""
    b = make_borders(n_cols=NCOLS)
    b.top_frame_kind = "single"
    b.bottom_frame_kind = "single"
    m = _run_gate(tmp_path, b)
    assert m.admitted
    assert not any(f.startswith("outer_frame_missing") for f in m.flags), m.flags


def test_wandering_vline_flags_not_blocks(tmp_path):
    """单条界行 w80 跑飞只 flag——没有"超了就该整页作废"的已验证判准，
    标出来供人复核，不拦。"""
    from open_guji_cv.gates.border_detect_gate import BorderDetectGateParams

    b = make_borders(n_cols=NCOLS)
    b.bend_w80_max = BorderDetectGateParams().bend_w80_max_gate + 1.0
    m = _run_gate(tmp_path, b)
    assert m.admitted, f"w80 跑飞不该 block：{m.reject}"
    assert any(f.startswith("vline_wander") for f in m.flags), m.flags


def test_missing_borders_product_is_a_tolerant_reject(tmp_path):
    """上游 borders 缺失时给一条说得清的 reject，而不是去读原图再抛异常
    ——缺产物往往就是因为原图本身缺失，这条分支要的是宽容报错。"""
    ctx = make_ctx(tmp_path, make_book(expected_cols=NCOLS))
    m = STEPS["border_detect_gate"].run_page(ctx, PAGE)["border_detect_gate_manifest"]
    assert not m.admitted
    assert any(r.startswith("missing_input") for r in m.reject), m.reject


def test_bend_w80_uses_same_constant_as_detection():
    """闸1的 w80 阈值必须与探测阶段判「单条线跑飞」用的是同一个常量——
    不各写一份阈值（Step0 闸0 的教训：文档说的量和代码实际算的量对不上）。"""
    from open_guji_cv.gates.border_detect_gate import BorderDetectGateParams
    from open_guji_cv.utils.border_geometry import BEND_W80_MAX
    assert BorderDetectGateParams().bend_w80_max_gate == BEND_W80_MAX
