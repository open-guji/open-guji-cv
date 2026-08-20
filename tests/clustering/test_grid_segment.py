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


def test_page_shared_grid_aligns_sparse_column():
    """整版同刻先验：稀疏列（只有 1 个字）跟随全页网格，不独立漂移。

    构造带 offset=25 网格的密列 ×2 + 稀疏列 ×1（仅第 3 格有字）。
    稀疏列若独立拟合会把唯一的字放进错误的格；共享网格下它必须
    与密列同格线，且唯一的字落在 index=3。
    """
    n, cell_h, width, off = 8, 60, 50, 25
    page_h = n * cell_h + 80
    page = np.full((page_h, 300), 235, dtype=np.uint8)
    frame_top, frame_bottom = 10, 10 + n * cell_h + off + 5
    cols = [(240, 290), (170, 220), (100, 150)]   # 右→左：密、密、稀
    for ci, (lx, rx) in enumerate(cols):
        for i in range(n):
            if ci == 2 and i != 3:
                continue
            y0 = frame_top + off + i * cell_h + 10
            page[y0:y0 + 40, lx + 8:rx - 8] = 25
    layout = {"borders": {"inner_frame": {
                  "top": {"intercept": frame_top},
                  "bottom": {"intercept": frame_bottom}}},
              "columns": {"columns": [
                  {"index": k + 1, "left_x": float(lx), "right_x": float(rx)}
                  for k, (lx, rx) in enumerate(cols)]}}
    result = GridSegmenter(chars_per_line=n).segment_page(page, layout)
    cols_out = {c["index"]: c for c in result["columns"]}

    sparse = [c for c in cols_out[3]["cells"] if c["type"] == "char"]
    assert len(sparse) == 1
    assert sparse[0]["index"] == 3
    # 稀疏列与密列的网格线一致（同 index 的格 y_top 相差 < 6px）
    dense_cells = {c["index"]: c for c in cols_out[1]["cells"]
                   if c["type"] != "margin"}
    sparse_cells = {c["index"]: c for c in cols_out[3]["cells"]
                    if c["type"] != "margin"}
    for i in range(n):
        assert abs(dense_cells[i]["y_top"] - sparse_cells[i]["y_top"]) < 6


def test_leading_blank_cells_keep_grid_anchor():
    """抬头空格：列首 2 格空时网格仍锚定页面栏格，不按内容上移。

    刻本栏格固定，空格占格位——若网格按该列内容顶端锚定，
    整列会错位两格（"乾隆…"抬头列的真实场景）。
    """
    n, cell_h = 8, 60
    page_h = n * cell_h + 40
    page = np.full((page_h, 260), 235, dtype=np.uint8)
    frame_top, frame_bottom = 20, 20 + n * cell_h
    cols = [(200, 250), (130, 180), (60, 110)]
    for ci, (lx, rx) in enumerate(cols):
        start = 2 if ci == 1 else 0   # 中间列抬头空 2 格
        for i in range(start, n):
            y0 = frame_top + i * cell_h + 10
            page[y0:y0 + 40, lx + 8:rx - 8] = 25
    layout = {"borders": {"inner_frame": {
                  "top": {"intercept": frame_top},
                  "bottom": {"intercept": frame_bottom}}},
              "columns": {"columns": [
                  {"index": k + 1, "left_x": float(lx), "right_x": float(rx)}
                  for k, (lx, rx) in enumerate(cols)]}}
    result = GridSegmenter(chars_per_line=n).segment_page(page, layout)
    cols_out = {c["index"]: c for c in result["columns"]}
    blank_col = [c for c in cols_out[2]["cells"] if c["type"] != "margin"]
    # 前 2 格 empty，后 6 格 char，且与满列同格线对齐
    assert [c["type"] for c in blank_col] == ["empty"] * 2 + ["char"] * 6
    full_col = [c for c in cols_out[1]["cells"] if c["type"] != "margin"]
    for a, b in zip(blank_col, full_col):
        assert abs(a["y_top"] - b["y_top"]) < 6


def test_rigid_grid_uniform_cell_height():
    """刚性网格：格高固定——所有格高度一致（±步长误差）。"""
    n = 8
    col = _make_column(n, jitter=5)
    page = np.full((col.shape[0] + 40, 140, ), 235, dtype=np.uint8)
    page[20:20 + col.shape[0], 45:45 + col.shape[1]] = col
    layout = {"borders": {"inner_frame": {
                  "top": {"intercept": 20},
                  "bottom": {"intercept": 20 + col.shape[0]}}},
              "columns": {"columns": [
                  {"index": 1, "left_x": 40.0, "right_x": 100.0}]}}
    result = GridSegmenter(chars_per_line=n).segment_page(page, layout)
    cells = [c for c in result["columns"][0]["cells"] if c["type"] != "margin"]
    heights = [c["y_bottom"] - c["y_top"] for c in cells]
    assert max(heights) - min(heights) < 1e-6


def test_column_grid_fitting():
    """列网格拟合（n_cols 模式）：不依赖 layout 列，自动定位文字带。

    合成页：3 个等距文字列 + 列间界行竖线 + 上下边框横线；
    其中中间列抬头空 3 格。断言：3 列全找到、边界落在文字带
    （不含界行）、空格判 empty、跨列同格线。
    """
    n_chars, cell_h, n_cols = 6, 60, 3
    period, text_w = 90, 60
    H, W = n_chars * cell_h + 60, n_cols * period + 60
    page = np.full((H, W), 235, dtype=np.uint8)
    frame_top = 30
    x0 = 30
    for k in range(n_cols):
        lx = x0 + k * period + (period - text_w) // 2
        start = 3 if k == 1 else 0
        for i in range(start, n_chars):
            y0 = frame_top + i * cell_h + 10
            page[y0:y0 + 40, lx + 6:lx + text_w - 6] = 25
        # 界行竖线（列格右边界处）
        page[frame_top:frame_top + n_chars * cell_h,
             x0 + (k + 1) * period - 1:x0 + (k + 1) * period + 1] = 25
    # 上下边框横线
    page[frame_top - 6:frame_top - 3, x0:x0 + n_cols * period] = 25
    page[frame_top + n_chars * cell_h + 3:frame_top + n_chars * cell_h + 6,
         x0:x0 + n_cols * period] = 25

    layout = {"borders": {"inner_frame": {
                  "top": {"intercept": frame_top},
                  "bottom": {"intercept": frame_top + n_chars * cell_h}}}}
    seg = GridSegmenter(chars_per_line=n_chars, n_cols=n_cols)
    result = seg.segment_page(page, layout)
    cols = [c for c in result["columns"] if not c.get("skipped")]
    assert len(cols) == n_cols
    # 列边界落在文字带内侧（不裹界行）：界行 x 不在 [left_x, right_x]
    for k, c in enumerate(sorted(cols, key=lambda c: c["left_x"])):
        rule_x = x0 + (k + 1) * period
        assert c["right_x"] < rule_x - 1
        # 文字带定位精度 ±20px（缝内相位自由度）；下游提取内缩 +
        # 归一化稳健外接框可吸收
        lx = x0 + k * period + (period - text_w) // 2
        assert abs(c["left_x"] - lx) < 20
        assert abs(c["right_x"] - (lx + text_w)) < 20
    # 中间列抬头 3 空格 + 跨列同格线
    mid = sorted(cols, key=lambda c: c["left_x"])[1]
    cells = [c for c in mid["cells"] if c["type"] != "margin"]
    assert [c["type"] for c in cells] == ["empty"] * 3 + ["char"] * 3
    first = sorted(cols, key=lambda c: c["left_x"])[0]
    fcells = [c for c in first["cells"] if c["type"] != "margin"]
    for a, b in zip(cells, fcells):
        assert abs(a["y_top"] - b["y_top"]) < 6


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
        # 全图坐标：cells 落在 inner_frame 外扩半格的范围内
        # （纵向裁切外扩半格容忍边框检测偏差，实际范围由投影内容决定）
        pad = 60 // 2 + 2
        assert all(20 - pad <= c["y_top"] <= 20 + n * 60 + pad for c in chars)
