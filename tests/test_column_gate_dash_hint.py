# -*- coding: utf-8 -*-
"""兜底 `n_raised_hint` 的「虚线残段」护栏（`hint_ignore_dash`，默认关）。

背景（S2 道，2026-10-02）：列图顶端偶尔留着版框内侧那条虚线的几行残墨，离首字
隔着一两格空白。兜底 hint 量「首末墨行的跨度装得下几格」，残段把跨度撑大 2 格，
凭空多出一格抬头（vol03 p28c2：跨度/period 21.68 → hint=1，剥掉残段后 19.4）。

数据全部自造：`trim_dash_ends` 直接喂掩码；端到端用 `synth_page` 画好页再往列顶
补一小簇虚线。
"""

from __future__ import annotations

import numpy as np

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from helpers import make_book, run_border_to_column_gate, synth_page

from open_guji_cv.gates.column_gate import ColumnGateParams, trim_dash_ends

PERIOD = 100.0
ARGS = (0.3, 1.2, 0.25)          # = 参数默认值


def _mask(n: int, *runs: tuple[int, int]) -> np.ndarray:
    m = np.zeros(n, bool)
    for a, b in runs:
        m[a:b + 1] = True
    return m


# ── trim_dash_ends：纯函数 ──────────────────────────────────


def test_leading_dash_cluster_is_trimmed():
    """两小段（4 行 + 6 行、相隔 12 行）并成一簇，后接 250 行空白才是正文 → 剥掉。"""
    m = _mask(2400, (5, 8), (21, 26), (290, 2300))
    assert trim_dash_ends(m, PERIOD, *ARGS) == (290, 2300)


def test_trailing_dash_is_trimmed_too():
    m = _mask(2600, (20, 2000), (2300, 2305))
    assert trim_dash_ends(m, PERIOD, *ARGS) == (20, 2000)


def test_real_first_char_is_kept():
    """真首字：簇跨度大（90 行）→ 不剥。"""
    m = _mask(2400, (5, 8), (120, 210), (330, 2300))
    # 5~8 是薄簇但后接空隙只有 111 行 < 1.2 格 → 也不剥（保守）
    assert trim_dash_ends(m, PERIOD, *ARGS) == (5, 2300)


def test_thin_mark_close_to_text_is_kept():
    """薄墨紧贴下一字（空隙 40 行）不是孤立虚线，不剥。"""
    m = _mask(2400, (100, 108), (150, 250), (300, 2300))
    assert trim_dash_ends(m, PERIOD, *ARGS) == (100, 2300)


def test_single_run_is_never_trimmed():
    m = _mask(500, (10, 14))
    assert trim_dash_ends(m, PERIOD, *ARGS) == (10, 14)


def test_empty_mask_gives_none():
    assert trim_dash_ends(np.zeros(100, bool), PERIOD, *ARGS) is None


# ── 端到端：闸 ──────────────────────────────────────────────

NCOLS = 9
DASH_COL = 5          # synth_page 的列号（xs 从右数）


def _page_with_dash():
    """9 列、每列 9 字（版式 10 格），列顶再补一簇 3 行厚的虚线残段。

    字块从 top_gap=2 格处起，**字本身**跨度 ~9 格 → 不该有 hint；
    残段在列顶，把「首末墨行」撑到 ~11 格 → 兜底 hint 误判 1。
    """
    gray, borders = synth_page(period=100, n_chars=9, top_gap=200)
    h, w = gray.shape
    # 找 DASH_COL 对应的列：取页宽 9 列中第 5 列的中线
    xs = np.linspace(60, w - 60, NCOLS + 1)
    cx = int((xs[DASH_COL - 1] + xs[DASH_COL]) / 2)
    y0 = 40 + 6 + 8                                    # 上版框内沿再往下 8 行
    for dy in (0, 12):                                 # 成簇：两小段
        gray[y0 + dy:y0 + dy + 3, cx - 30:cx + 30] = 20
    return gray, borders


def _run(tmp_path, gray, borders, *, ignore_dash: bool) -> dict[int, int]:
    from helpers import make_ctx, make_gate1, run_steps

    book = make_book(expected_cols=NCOLS, chars_per_line=10)
    ctx = make_ctx(tmp_path, book, raw={1: gray})
    if ignore_dash:
        ctx.params["column_gate"] = ColumnGateParams(hint_ignore_dash=True)
    ctx.store.write(book.id, "border_detect", "p0001", {"borders": borders})
    ctx.store.write(book.id, "border_detect_gate", "p0001",
                    {"border_detect_gate_manifest": make_gate1(
                        1, n_cols=borders.expected_cols, expected_cols=book.expected_cols)})
    out = run_steps(ctx, 1, ["column_warp", "column_gate"])
    return {c.col: c.n_raised_hint for c in out["gate_manifest"].columns}


def test_default_is_off_and_dash_still_inflates_hint(tmp_path):
    assert ColumnGateParams().hint_ignore_dash is False
    gray, borders = _page_with_dash()
    hints = _run(tmp_path, gray, borders, ignore_dash=False)
    assert max(hints.values()) >= 1, f"造的残段没把兜底 hint 撑起来，测试场景失效：{hints}"


def test_switch_on_removes_dash_hint_and_touches_nothing_else(tmp_path):
    gray, borders = _page_with_dash()
    off = _run(tmp_path / "off", gray, borders, ignore_dash=False)
    on = _run(tmp_path / "on", gray, borders, ignore_dash=True)
    assert all(v == 0 for v in on.values()), f"开关开着仍有假 hint：{on}"
    assert {k for k in off if off[k] != on[k]} == {k for k, v in off.items() if v > 0}


def test_switch_on_keeps_a_genuine_extra_char(tmp_path):
    """真多一个字（顶格上方再写一字）开着开关也要保住 hint=1。"""
    gray, borders = synth_page(period=120, n_chars=10, top_gap=120,
                               col_top_gap={1: 0}, col_n_chars={1: 11})
    hints = _run(tmp_path, gray, borders, ignore_dash=True)
    assert hints[9] == 1, f"开关把真多一字的 hint 吃掉了：{hints}"
    assert all(v == 0 for k, v in hints.items() if k != 9), hints
