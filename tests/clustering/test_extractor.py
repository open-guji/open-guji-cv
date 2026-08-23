"""extractor.py 单测：合成 grid JSON + 合成页面 → 提取正确性。"""

import numpy as np

from open_guji_cv.clustering.extractor import CharExtractor


def _make_page_and_grid():
    """构造 200×300 白底页面：2 列 × 每列 3 个字块（暗色矩形）。"""
    page = np.full((300, 200), 235, dtype=np.uint8)
    columns = []
    # 列 1（右侧）x∈[120,180]，列 2（左侧）x∈[20,80]
    for col_no, (lx, rx) in [(1, (120.0, 180.0)), (2, (20.0, 80.0))]:
        cells = [{"type": "margin", "y_top": 0.0, "y_bottom": 10.0}]
        y = 10.0
        for idx in range(3):
            y_top, y_bottom = y, y + 60.0
            page[int(y_top) + 8:int(y_bottom) - 8,
                 int(lx) + 8:int(rx) - 8] = 30   # 墨块
            cells.append({"type": "char", "index": idx,
                          "y_top": y_top, "y_bottom": y_bottom,
                          "text": "字", "confidence": 0.9})
            y = y_bottom + 5.0
        cells.append({"type": "empty", "index": 3,
                      "y_top": y, "y_bottom": y + 60.0,
                      "text": None, "confidence": 0.0})
        columns.append({"index": col_no, "left_x": lx, "right_x": rx,
                        "cells": cells})
    grid = {"columns": columns}
    return page, grid


def test_extract_counts_and_ids():
    page, grid = _make_page_and_grid()
    results = CharExtractor().extract_page(page, grid, "bookX", "5")
    assert len(results) == 6  # 2 列 × 3 char（empty/margin 不提取）
    ids = [inst.id for inst, _ in results]
    assert len(set(ids)) == 6
    assert "bookX:5:1:0" in ids
    assert "bookX:5:2:2" in ids


def test_padding_and_bounds():
    page, grid = _make_page_and_grid()
    extractor = CharExtractor(padding_ratio=0.1)
    for inst, patch in extractor.extract_page(page, grid, "b", "1"):
        x0, y0, x1, y1 = inst.bbox
        # bbox 在图内
        assert 0 <= x0 < x1 <= page.shape[1]
        assert 0 <= y0 < y1 <= page.shape[0]
        # 垂直外扩（笔画出头）；水平内缩（列边界即界行，不裹进来）
        assert (y1 - y0) > inst.height
        assert (x1 - x0) < inst.width
        assert patch.shape == (int(round(y1)) - int(round(y0)),
                               int(round(x1)) - int(round(x0)))


def test_ink_ratio_and_flags():
    page, grid = _make_page_and_grid()
    # 把列 1 第 0 个字块清空 → 应标 suspect_empty
    page[18:62, 128:172] = 235
    results = CharExtractor().extract_page(page, grid, "b", "1")
    by_id = {inst.id: inst for inst, _ in results}
    assert "suspect_empty" in by_id["b:1:1:0"].flags
    assert by_id["b:1:1:1"].ink_ratio > 0.2
    assert not by_id["b:1:1:1"].flags


def test_instance_json_roundtrip():
    from open_guji_cv.clustering.extractor import CharInstance
    page, grid = _make_page_and_grid()
    inst, _ = CharExtractor().extract_page(page, grid, "b", "1")[0]
    restored = CharInstance.from_json(inst.to_json())
    assert restored == inst


def test_edge_blob_spares_a_detached_part_of_the_character():
    """「冬」的下两点整体落在底部带内、但贴着主体——那是本字，不是残余。

    格线吸附收紧图块后这类部件常顶到边缘带；没有间隙条件时它被误判，
    确定层的零误报因此失守（实测 vol01/10:2:6）。
    """
    import numpy as np
    from open_guji_cv.clustering.extractor import _defect_features
    g = np.full((140, 150), 255, np.uint8)
    g[20:110, 20:130] = 0                 # 主体
    g[114:132, 60:90] = 0                 # 分离部件：距主体 4px（0.03h），在底部带内
    assert _defect_features(g)["edge_blob"] == 0.0


def test_edge_blob_still_fires_on_a_far_neighbor_residue():
    """真残余隔着整条字间空白（实测 +0.206×图块高），必须仍然报。"""
    import numpy as np
    from open_guji_cv.clustering.extractor import _defect_features
    g = np.full((140, 150), 255, np.uint8)
    g[40:105, 20:130] = 0                 # 主体
    g[2:18, 40:110] = 0                   # 顶部残余：距主体 22px（0.16h）
    assert _defect_features(g)["edge_blob"] > 0.03


def _jiazhu_patch(w=120, h=110):
    """两列并排的小字块：合起来占满列宽，中缝 6px。"""
    import numpy as np
    g = np.full((h, w), 255, np.uint8)
    g[20:90, 8:55] = 0          # 左子列
    g[15:85, 61:112] = 0        # 右子列
    return g


def test_jiazhu_gap_center_fires_on_side_by_side_small_chars():
    from open_guji_cv.clustering.extractor import _jiazhu_gap_center
    c = _jiazhu_gap_center(_jiazhu_patch())
    assert c is not None and 50 < c < 66, c


def test_jiazhu_gap_center_spares_a_normal_radical_char():
    """左右结构字（部/郎）：单字只占 ~0.7 列宽，span 条件挡住。"""
    import numpy as np
    from open_guji_cv.clustering.extractor import _jiazhu_gap_center
    g = np.full((110, 120), 255, np.uint8)
    g[10:100, 25:55] = 0        # 左部首
    g[10:100, 58:85] = 0        # 右部首（总跨度 0.5w）
    assert _jiazhu_gap_center(g) is None


def test_flag_jiazhu_runs_requires_consecutive_aligned_cells():
    from open_guji_cv.clustering.extractor import flag_jiazhu_runs
    # 连续三格缝对齐 → 全标；孤立一格 → 不标；缝错开 → 不标
    assert flag_jiazhu_runs([(0, 60.0), (1, 62.0), (2, 58.0)]) == {0, 1, 2}
    assert flag_jiazhu_runs([(0, 60.0), (2, 60.0)]) == set()
    assert flag_jiazhu_runs([(0, 60.0), (1, 90.0)]) == set()
