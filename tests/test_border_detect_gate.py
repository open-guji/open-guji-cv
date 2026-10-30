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
    from open_guji_cv.seg.polyline import BEND_W80_MAX
    assert BorderDetectGateParams().bend_w80_max_gate == BEND_W80_MAX


def _run_gate_params(tmp_path, monkeypatch, params, verdict):
    """页型规则打桩成 `verdict`，带册级 `params` 跑闸1。"""
    import open_guji_cv.gates.border_detect_gate as bdg
    monkeypatch.setattr(bdg, "classify_page_type", lambda raw: verdict)
    ctx = make_ctx(tmp_path, make_book(params=params), raw={PAGE: body_page(n_cols=NCOLS)})
    ctx.store.write(ctx.book.id, "border_detect", f"p{PAGE:04d}", {"borders": make_borders(n_cols=NCOLS)})
    return STEPS["border_detect_gate"].run_page(ctx, PAGE)["border_detect_gate_manifest"]


def test_body_pages_overrides_page_type_skip(tmp_path, monkeypatch):
    """册配置 body_pages 点名的页：页型规则判 cover/skip 也按正文走，并留 flag（vol06 p88）。"""
    m = _run_gate_params(tmp_path, monkeypatch, {"border_detect_gate": {"body_pages": [PAGE]}},
                         ("cover", "skip"))
    assert m.admitted, m.reject
    assert (m.page_type, m.page_type_policy) == ("body", "standard")
    assert any(f.startswith("page_type_forced") for f in m.flags)


def test_body_pages_other_page_still_skipped(tmp_path, monkeypatch):
    m = _run_gate_params(tmp_path, monkeypatch, {"border_detect_gate": {"body_pages": [PAGE + 1],
                                                                        "grid_overrides_skip": False}},
                         ("cover", "skip"))
    assert not m.admitted and m.page_type == "cover"
    assert not any(f.startswith("page_type_forced") for f in m.flags)


def test_body_pages_empty_not_in_params_dump():
    """缺省空时不进参数 dump：指纹与加字段前相同。"""
    from open_guji_cv.gates.border_detect_gate import BorderDetectGateParams
    assert "body_pages" not in BorderDetectGateParams().model_dump()
    assert BorderDetectGateParams(body_pages=[88]).model_dump()["body_pages"] == [88]


def test_full_uniform_grid_overrides_page_type_skip(tmp_path, monkeypatch):
    """页型规则判 label/skip，但探出完整等宽的 9 列栏格：卷末少字页，按正文走并留 flag
    （殿本 vol13 p89、vol14 p174 整页没切，2026-10-25）。"""
    m = _run_gate_params(tmp_path, monkeypatch, {}, ("label", "skip"))
    assert m.admitted, m.reject
    assert (m.page_type, m.page_type_policy) == ("body", "standard")
    assert any(f.startswith("page_type_grid") for f in m.flags)


def test_uneven_grid_still_skipped(tmp_path, monkeypatch):
    """列数凑对了但列宽乱（题签、封面上的杂线）照旧跳过（vol20 p179）。"""
    import open_guji_cv.gates.border_detect_gate as bdg
    monkeypatch.setattr(bdg, "classify_page_type", lambda raw: ("label", "skip"))
    xs = [60, 100, 300, 320, 400, 470, 560, 640, 700, 840]
    ctx = make_ctx(tmp_path, make_book(), raw={PAGE: body_page(n_cols=NCOLS)})
    ctx.store.write(ctx.book.id, "border_detect", f"p{PAGE:04d}", {"borders": make_borders(n_cols=NCOLS, xs=xs)})
    m = STEPS["border_detect_gate"].run_page(ctx, PAGE)["border_detect_gate_manifest"]
    assert not m.admitted and m.page_type == "label"
    assert not any(f.startswith("page_type_grid") for f in m.flags)


def _run_grid_case(tmp_path, monkeypatch, *, raw=None, borders=None):
    import open_guji_cv.gates.border_detect_gate as bdg
    monkeypatch.setattr(bdg, "classify_page_type", lambda raw: ("label", "skip"))
    ctx = make_ctx(tmp_path, make_book(), raw={PAGE: body_page(n_cols=NCOLS) if raw is None else raw})
    ctx.store.write(ctx.book.id, "border_detect", f"p{PAGE:04d}",
                    {"borders": make_borders(n_cols=NCOLS) if borders is None else borders})
    return STEPS["border_detect_gate"].run_page(ctx, PAGE)["border_detect_gate_manifest"]


def test_grid_lines_missing_on_the_image_still_skipped(tmp_path, monkeypatch):
    """产物里栏格完整等宽，原图上却没有界行（框线残留、装订线误检）：不放。"""
    import numpy as np
    m = _run_grid_case(tmp_path, monkeypatch, raw=np.full_like(body_page(n_cols=NCOLS), 255))
    assert not m.admitted and m.page_type == "label"


def test_interpolated_grid_lines_still_skipped(tmp_path, monkeypatch):
    """网格模式插值补出来的竖线不算探到。"""
    b = make_borders(n_cols=NCOLS)
    b.vline_filled = [False] * len(b.verticals)
    b.vline_filled[3] = True
    m = _run_grid_case(tmp_path, monkeypatch, borders=b)
    assert not m.admitted and m.page_type == "label"


def test_few_vertical_lines_still_skipped(tmp_path, monkeypatch):
    """横页、题签只探到 4 条竖线（殿本 vol04 第 129 叶）：列数对不上，照旧跳过。"""
    m = _run_grid_case(tmp_path, monkeypatch, borders=make_borders(n_cols=3))
    assert not m.admitted and m.page_type == "label"
    assert not any(f.startswith("page_type_grid") for f in m.flags)
