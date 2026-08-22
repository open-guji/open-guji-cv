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
        assert abs(c["left_x"] - lx) < 20, (k, c["left_x"], lx)
        assert abs(c["right_x"] - (lx + text_w)) < 20, (k, c["right_x"], lx)
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


# ── cells_from_components / _split_dense_segment：拉开列 + 压缩超载列 ──

from open_guji_cv.clustering.grid_segment import (  # noqa: E402
    GridParams, cells_from_components, _split_dense_segment)


def _compressed_group(n_sub_chars, char_h, gap, width=50, pad=6):
    """一段"压缩标题"：多个小字紧挨着（间隙小于合并阈值），整体是一个
    连通体，但内部仍有墨量谷点——_split_dense_segment 应该切得出来。"""
    h = n_sub_chars * (char_h + gap) - gap
    seg = np.full((h, width), 235, dtype=np.uint8)
    y = 0
    for _ in range(n_sub_chars):
        seg[y:y + char_h, pad:width - pad] = 25
        y += char_h + gap
    return seg


def test_split_dense_segment_finds_compressed_characters():
    """压缩段（字间隙小于合并阈值）内部仍能按谷点切出正确字数。"""
    cell_h = 60.0
    seg = _compressed_group(n_sub_chars=6, char_h=20, gap=8)
    boxes = _split_dense_segment(seg, 0.0, float(seg.shape[0]), cell_h)
    assert len(boxes) == 6


def test_split_dense_segment_falls_back_when_no_valleys():
    """真连笔（内部无墨量谷点）时按格高均分兜底，不比旧行为差。"""
    cell_h = 60.0
    h = int(3 * cell_h)
    seg = np.full((h, 50), 25, dtype=np.uint8)   # 通体是墨，没有任何谷
    boxes = _split_dense_segment(seg, 0.0, float(h), cell_h)
    assert len(boxes) == 3                        # 按 0.95×格高均分


def _spread_and_overflow_column(cell_h=60.0, width=50):
    """合成一列：既有拉开的官衔字，又有一段压缩标题（子字符数超过
    n_chars）——用来验证超载列不再被 len(boxes) > n_chars 一票否决。"""
    n_chars = 9
    L = int(15 * cell_h)
    col = np.full((L, width), 235, dtype=np.uint8)

    def put_char(y0, h=int(0.9 * cell_h)):
        col[y0:y0 + h, 6:width - 6] = 25

    # 3 个拉开的单字（官衔），彼此间隙 > 2.2 格
    put_char(int(0.2 * cell_h))
    put_char(int(3.0 * cell_h))
    put_char(int(6.0 * cell_h))
    # 一段压缩标题：11 个小字紧密排列（单字 ~0.5 格，仍比 min_h 大），
    # 子字符总数 11 > n_chars(9)
    group_top = int(9.0 * cell_h)
    group = _compressed_group(n_sub_chars=11, char_h=25, gap=5, width=width)
    col[group_top:group_top + group.shape[0], :] = group
    return col, n_chars


def test_cells_from_components_supports_overflow_column():
    """超载列（真实字数 > n_chars）不再被打回刚性网格，格数就是真实字数。"""
    cell_h = 60.0
    col, n_chars = _spread_and_overflow_column(cell_h)
    params = GridParams(n_chars, 0.02, 0.5)
    cells = cells_from_components(col, cell_h, n_chars, params)
    assert cells is not None
    assert len(cells) > n_chars                  # 3 拉开字 + 11 压缩字 = 14
    assert [c["index"] for c in cells] == list(range(len(cells)))
    assert all(c["type"] == "char" for c in cells)


def test_cells_from_components_still_rejects_dense_normal_column():
    """密排正文列（组件少、间隙都小）依旧不触发，走刚性网格。"""
    cell_h = 60.0
    col = _make_column(n_chars=9, cell_h=int(cell_h))
    params = GridParams(9, 0.02, 0.5)
    assert cells_from_components(col, cell_h, 9, params) is None


# ── 残余错切校正 ──────────────────────────────────────────

def _ruled_page(tan_t=0.0, h=1600, w=900, period=180):
    """造一张带斜界行的页：竖线按 dx/dy = tan_t 走。

    尺寸取真实量级（真页约 2500×1700、周期 180、界行 2~3px）。缩得太小
    时倾斜在一个形态学核高度内的漂移不足一个线宽，竖线其实没被打断，
    目标函数就变平——那是测试造得不像，不是算法不灵。
    """
    import numpy as np
    g = np.full((h, w), 255, np.uint8)
    for k in range(1, w // period):
        for y in range(h):
            x = int(k * period + tan_t * (y - h / 2))
            if 0 <= x < w:
                g[y, max(0, x - 1):x + 1] = 0
    return g


def test_rule_evidence_peaks_when_lines_are_vertical():
    from open_guji_cv.clustering.grid_segment import rule_evidence
    assert rule_evidence(_ruled_page(0.0)) > rule_evidence(_ruled_page(0.015))


def test_estimate_shear_recovers_the_tilt():
    from open_guji_cv.clustering.grid_segment import estimate_shear
    t = estimate_shear(_ruled_page(0.010))
    assert abs(t - 0.010) < 0.003, t


def test_estimate_shear_returns_zero_on_straight_page():
    """没错切就别动——never-make-worse 是这一步的硬约束。"""
    from open_guji_cv.clustering.grid_segment import estimate_shear
    assert estimate_shear(_ruled_page(0.0)) == 0.0


def test_deshear_straightens_the_rules():
    from open_guji_cv.clustering.grid_segment import (deshear, estimate_shear,
                                                      rule_evidence)
    tilted = _ruled_page(0.012)
    fixed = deshear(tilted, estimate_shear(tilted))
    assert rule_evidence(fixed) > 3 * rule_evidence(tilted)


def test_deshear_matches_between_modules():
    """extractor 复制了同一个变换（避免循环 import），两边必须完全一致。"""
    import numpy as np
    from open_guji_cv.clustering.grid_segment import deshear
    from open_guji_cv.clustering.extractor import _deshear
    g = _ruled_page(0.008)
    assert np.array_equal(deshear(g, 0.008), _deshear(g, 0.008))


def test_deshear_is_identity_at_zero():
    import numpy as np
    from open_guji_cv.clustering.grid_segment import deshear
    g = _ruled_page(0.006)
    assert np.array_equal(deshear(g, 0.0), g)


def test_extract_page_applies_grid_shear():
    """chars 必须按 grid.shear 做同样的变换，否则列框整体错位。"""
    import json
    import numpy as np
    from open_guji_cv.clustering.extractor import CharExtractor
    from open_guji_cv.clustering.grid_segment import deshear

    # 一列字，整体按 tan=0.01 斜过去
    straight = np.full((400, 200), 235, np.uint8)
    straight[60:120, 80:140] = 25
    straight[200:260, 80:140] = 25
    tilted = deshear(straight, -0.01)      # 反向错切 = 造出斜页

    grid = {"grid": {"shear": -0.01},
            "columns": [{"index": 1, "left_x": 70.0, "right_x": 150.0,
                         "cells": [{"type": "char", "index": 0,
                                    "y_top": 50.0, "y_bottom": 150.0},
                                   {"type": "char", "index": 1,
                                    "y_top": 190.0, "y_bottom": 290.0}]}]}
    res = CharExtractor().extract_page(tilted, grid, "b", "1")
    inks = [float((p < 128).mean()) for _, p in res]
    assert len(res) == 2 and all(i > 0.05 for i in inks), inks


# ── 用界行钉住列相位 ──────────────────────────────────────

def _vproj(g):
    from open_guji_cv.clustering.grid_segment import page_column_projection
    return page_column_projection(g)


def test_rule_segments_finds_the_rules():
    from open_guji_cv.clustering.grid_segment import rule_segments
    segs = rule_segments(_ruled_page(0.0, w=900, period=180))
    assert len(segs) == 4, segs          # w//period - 1 = 4 条


def test_rule_segments_blind_to_tilted_rules():
    """斜界行的覆盖率被摊薄，检不出——这正是必须先去错切的理由。"""
    from open_guji_cv.clustering.grid_segment import rule_segments
    assert len(rule_segments(_ruled_page(0.015))) < 2


def test_snap_moves_column_phase_onto_the_rules():
    from open_guji_cv.clustering.grid_segment import snap_columns_to_rules
    g = _ruled_page(0.0, w=900, period=180)
    # 故意把列格起点偏 40px，列框就会把界行圈进去
    cx0, il, ir = snap_columns_to_rules(g, _vproj(g), 180 - 40, 180.0, 4, 12.0, 12.0)
    assert abs(((cx0 - 180) + 90) % 180 - 90) < 6, cx0


def test_snap_widens_inset_to_clear_the_rule():
    from open_guji_cv.clustering.grid_segment import snap_columns_to_rules
    g = _ruled_page(0.0, w=900, period=180)
    _, il, ir = snap_columns_to_rules(g, _vproj(g), 180.0, 180.0, 4, 0.0, 0.0)
    assert il >= 3.0 and ir >= 3.0, (il, ir)


def test_snap_is_a_noop_without_enough_rules():
    import numpy as np
    from open_guji_cv.clustering.grid_segment import snap_columns_to_rules
    blank = np.full((1600, 900), 255, np.uint8)
    assert snap_columns_to_rules(blank, _vproj(blank), 7.0, 180.0, 4, 11.0, 13.0) \
        == (7.0, 11.0, 13.0)


def test_snap_never_makes_it_worse():
    """相位本来就对时不许乱动——择优是这一步的硬约束。"""
    from open_guji_cv.clustering.grid_segment import (rule_segments,
                                                      snap_columns_to_rules,
                                                      _comb, _rule_in_col)
    g = _ruled_page(0.0, w=900, period=180)
    segs = rule_segments(g)
    before = _rule_in_col(segs, _comb(180.0, 180.0, 4, 12.0, 12.0))
    cx0, il, ir = snap_columns_to_rules(g, _vproj(g), 180.0, 180.0, 4, 12.0, 12.0)
    assert _rule_in_col(segs, _comb(cx0, 180.0, 4, il, ir)) <= before



def test_column_geometry_at_real_column_count():
    """列几何在**真实列数**下的精度：9 列（真书每半页 9 列）。

    列太少时整页可用周期太少、拟出来的周期本身就偏（3 列拟成 78.9，
    真值 90），几何断言只能放到 ±20px，测不出真问题。这里只断言列
    几何，不碰行网格——6 行的合成页会让行周期锁到谐波（27.5 vs 60），
    那是稀疏页的已知问题，真书靠书级格高共识兜住，单页测试里没有。
    """
    n_chars, cell_h, n_cols = 6, 60, 9
    period, text_w = 90, 60
    H, W = n_chars * cell_h + 60, n_cols * period + 60
    page = np.full((H, W), 235, dtype=np.uint8)
    frame_top, x0 = 30, 30
    for k in range(n_cols):
        lx = x0 + k * period + (period - text_w) // 2
        for i in range(n_chars):
            y = frame_top + i * cell_h + 10
            page[y:y + 40, lx + 6:lx + text_w - 6] = 25
        page[frame_top:frame_top + n_chars * cell_h,
             x0 + (k + 1) * period - 1:x0 + (k + 1) * period + 1] = 25
    layout = {"borders": {"inner_frame": {
        "top": {"intercept": frame_top},
        "bottom": {"intercept": frame_top + n_chars * cell_h}}}}
    res = GridSegmenter(chars_per_line=n_chars, n_cols=n_cols).segment_page(
        page, layout)
    cols = sorted([c for c in res["columns"] if not c.get("skipped")],
                  key=lambda c: c["left_x"])
    assert len(cols) == n_cols
    assert res["grid"]["rule_in_col"] == 0.0
    for k, c in enumerate(cols):
        lx = x0 + k * period + (period - text_w) // 2
        assert abs(c["left_x"] - lx) < 15, (k, c["left_x"], lx)
        assert abs(c["right_x"] - (lx + text_w)) < 15, (k, c["right_x"], lx)
        # 两侧界行都不许落进列框
        for r in (x0 + k * period, x0 + (k + 1) * period):
            assert not (c["left_x"] <= r <= c["right_x"]), (k, r)
