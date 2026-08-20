"""grid_segment.py 单测：网格拟合恢复精度、判空、窄列过滤、契约兼容。"""

import numpy as np

from open_guji_cv.clustering.grid_segment import (GridParams, GridSegmenter,
                                                  fit_global_grid,
                                                  refine_boundaries,
                                                  segment_column)


def _make_column(n_chars=8, cell_h=60, width=50, ink_h=40, offset=0,
                 skip=(), jitter=None):
    """合成列：每格中央一个墨块（白底 235，墨 25）。skip 中的格留空。"""
    L = n_chars * cell_h
    col = np.full((L, width), 235, dtype=np.uint8)
    rng = np.random.default_rng(0)
    for i in range(n_chars):
        if i in skip:
            continue
        j = int(rng.integers(-jitter, jitter + 1)) if jitter else 0
        y0 = offset + i * cell_h + (cell_h - ink_h) // 2 + j
        col[max(0, y0):max(0, y0) + ink_h, 5:width - 5] = 25
    return col


def test_fit_global_grid_recovers_offset():
    n, cell_h = 8, 60
    col = _make_column(n, cell_h)
    proj = (col < 128).sum(axis=1).astype(float)
    off, h = fit_global_grid(proj, n)
    assert abs(h - cell_h) < cell_h * 0.05
    # 网格线应落在字间空隙：所有边界处投影为 0
    bounds = [off + h * k for k in range(n + 1)]
    for b in bounds[1:-1]:
        assert proj[int(b)] == 0


def test_refine_boundaries_monotonic_with_jitter():
    n, cell_h = 8, 60
    col = _make_column(n, cell_h, jitter=6)
    proj = (col < 128).sum(axis=1).astype(float)
    off, h = fit_global_grid(proj, n)
    bounds = refine_boundaries(proj, off, h, n)
    assert len(bounds) == n + 1
    diffs = np.diff(bounds)
    assert (diffs >= 0.6 * h - 1e-6).all()      # 格高不塌缩
    # 内部边界都落在空隙（投影为 0 的行）
    for b in bounds[1:-1]:
        assert proj[int(b)] == 0


def test_segment_column_char_and_empty():
    n = 8
    col = _make_column(n, skip={2, 5})
    cells = segment_column(col, n, GridParams(n))
    typed = [c for c in cells if c["type"] != "margin"]
    assert len(typed) == n
    assert [c["index"] for c in typed] == list(range(n))
    assert typed[2]["type"] == "empty"
    assert typed[5]["type"] == "empty"
    assert sum(1 for c in typed if c["type"] == "char") == n - 2
    # 相邻格无缝隙（网格切分的性质）
    for a, b in zip(typed, typed[1:]):
        assert abs(a["y_bottom"] - b["y_top"]) < 1e-6


def test_blank_column_all_empty():
    col = np.full((480, 50), 235, dtype=np.uint8)
    cells = segment_column(col, 8, GridParams(8))
    assert all(c["type"] == "empty" for c in cells)
    assert len(cells) == 8


def test_segment_page_contract_and_narrow_column_filter():
    """整页：正常列出 cells；窄列（版心缝）标记 skipped。"""
    n = 6
    page = np.full((n * 60 + 40, 300), 235, dtype=np.uint8)
    layout = {"borders": {"inner_frame": {
                  "top": {"intercept": 20},
                  "bottom": {"intercept": 20 + n * 60}}},
              "columns": {"columns": [
                  {"index": 1, "left_x": 200.0, "right_x": 260.0},
                  {"index": 2, "left_x": 180.0, "right_x": 195.0},   # 窄缝
                  {"index": 3, "left_x": 110.0, "right_x": 170.0},
              ]}}
    for lx, rx in [(200, 260), (110, 170)]:
        for i in range(n):
            y0 = 20 + i * 60 + 10
            page[y0:y0 + 40, lx + 8:rx - 8] = 25
    seg = GridSegmenter(chars_per_line=n)
    result = seg.segment_page(page, layout)
    assert result["chars_per_line"] == n
    cols = {c["index"]: c for c in result["columns"]}
    assert cols[2].get("skipped") == "non_text_column"
    assert not cols[2]["cells"]
    for idx in (1, 3):
        chars = [c for c in cols[idx]["cells"] if c["type"] == "char"]
        assert len(chars) == n
        # 全图坐标：cells 落在 inner_frame 范围内
        assert all(20 - 1 <= c["y_top"] <= 20 + n * 60 + 1 for c in chars)
