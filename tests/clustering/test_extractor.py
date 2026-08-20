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
