"""刻本严格网格切分（Phase 3 的替代实现，无 OCR 依赖）。

刻本古籍格式非常固定：每行严格 N 字、字高一致。据此把切分建模为
**网格拟合**而非自由投影分割：

1. 每列先验网格：[col_top, col_bottom] 均分为 N 格；
2. 全局微调：搜索 (偏移 δ, 伸缩 s)，使网格线尽量落在投影谷（字间空隙）；
3. 逐线微调：每条网格线在 ±search_ratio 格高内移到最近的投影谷，
   保持单调、格高不塌缩；
4. 格内判空：墨迹覆盖率 < empty_ink_ratio 的格为 empty。

断笔/磨损不会破坏切分——网格由整列证据共同决定，单字残损只影响该格判空。
输出与 CharGridDetector 相同的 char_grid JSON 契约，下游（M1 提取）无感。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..utils.image_io import imread
from .extractor import CharExtractor

BINARY_THRESHOLD = 128
EMPTY_INK_RATIO = 0.02     # 格内墨迹覆盖率低于此 → empty
MIN_COL_WIDTH_RATIO = 0.5  # 列宽低于中位列宽的此比例 → 非文字列（版心/界行缝），跳过
SEARCH_RATIO = 0.3         # 逐线微调搜索半径（× 格高）
SCALES = np.linspace(0.96, 1.04, 9)


@dataclass
class GridParams:
    chars_per_line: int
    empty_ink_ratio: float = EMPTY_INK_RATIO
    search_ratio: float = SEARCH_RATIO


def column_projection(col_gray: np.ndarray) -> np.ndarray:
    """列区域的水平投影（每行黑像素数）。输入灰度或二值图。"""
    binary = (col_gray < BINARY_THRESHOLD).astype(np.uint8)
    return binary.sum(axis=1).astype(np.float64)


def fit_global_grid(proj: np.ndarray, n_chars: int,
                    scales: np.ndarray = SCALES) -> tuple[float, float]:
    """全局网格拟合：搜索 (偏移 δ, 伸缩 s) 使 n_chars+1 条网格线的
    投影值之和最小（线落在字间空隙处）。

    Returns:
        (offset, cell_h): 首线位置与格高。
    """
    L = len(proj)
    base_h = L / n_chars
    # 投影平滑，避免单像素毛刺主导
    kernel = max(3, int(base_h * 0.08)) | 1
    smooth = np.convolve(proj, np.ones(kernel) / kernel, mode="same")

    best = (0.0, base_h)
    best_cost = float("inf")
    for s in scales:
        cell_h = base_h * s
        span = cell_h * n_chars
        max_off = L - span
        offsets = np.linspace(min(0.0, max_off), max(0.0, max_off),
                              num=15) if abs(max_off) > 1e-6 else [0.0]
        for off in offsets:
            lines = off + cell_h * np.arange(n_chars + 1)
            idx = np.clip(np.round(lines).astype(int), 0, L - 1)
            cost = float(smooth[idx].sum())
            if cost < best_cost:
                best_cost = cost
                best = (float(off), float(cell_h))
    return best


def refine_boundaries(proj: np.ndarray, offset: float, cell_h: float,
                      n_chars: int,
                      search_ratio: float = SEARCH_RATIO) -> list[float]:
    """逐线微调：每条内部网格线在 ±search_ratio×格高 内移到投影最低点。

    首尾线不动（列边界）；保持单调且相邻线距 ≥ 0.6×格高。
    """
    L = len(proj)
    kernel = max(3, int(cell_h * 0.08)) | 1
    smooth = np.convolve(proj, np.ones(kernel) / kernel, mode="same")

    lines = [offset + cell_h * k for k in range(n_chars + 1)]
    refined = [lines[0]]
    for k in range(1, n_chars):
        y = lines[k]
        r = cell_h * search_ratio
        lo = max(int(y - r), int(refined[-1] + 0.6 * cell_h))
        hi = min(int(y + r), L - 1)
        if hi <= lo:
            refined.append(max(y, refined[-1] + 0.6 * cell_h))
            continue
        window = smooth[lo:hi + 1]
        # 同值谷取离先验位置最近者
        min_v = window.min()
        cand = np.nonzero(window <= min_v + 1e-9)[0] + lo
        best = cand[np.argmin(np.abs(cand - y))]
        refined.append(float(best))
    refined.append(lines[-1])
    return refined


def segment_column(col_gray: np.ndarray, n_chars: int,
                   params: GridParams) -> list[dict]:
    """单列切分 → cells（局部 y 坐标，调用方负责平移到全图）。"""
    proj = column_projection(col_gray)
    if proj.sum() < 1:   # 整列空白
        L = len(proj)
        cell = L / n_chars
        return [{"type": "empty", "index": i,
                 "y_top": i * cell, "y_bottom": (i + 1) * cell,
                 "text": None, "confidence": 0.0} for i in range(n_chars)]

    offset, cell_h = fit_global_grid(proj, n_chars)
    bounds = refine_boundaries(proj, offset, cell_h, n_chars,
                               params.search_ratio)

    w = col_gray.shape[1]
    cells: list[dict] = []
    if bounds[0] > 0.5:
        cells.append({"type": "margin", "y_top": 0.0, "y_bottom": bounds[0]})
    for i in range(n_chars):
        y0, y1 = bounds[i], bounds[i + 1]
        seg = (col_gray[int(y0):int(y1)] < BINARY_THRESHOLD)
        ink = float(seg.sum()) / max(1.0, (y1 - y0) * w)
        if ink < params.empty_ink_ratio:
            cells.append({"type": "empty", "index": i,
                          "y_top": y0, "y_bottom": y1,
                          "text": None, "confidence": 0.0})
        else:
            cells.append({"type": "char", "index": i,
                          "y_top": y0, "y_bottom": y1,
                          "text": None, "confidence": 0.0})
    L = len(proj)
    if bounds[-1] < L - 0.5:
        cells.append({"type": "margin", "y_top": bounds[-1],
                      "y_bottom": float(L)})
    return cells


class GridSegmenter:
    """刻本网格切分器：phase2 layout + 页面图 → char_grid JSON。"""

    def __init__(self, chars_per_line: int,
                 empty_ink_ratio: float = EMPTY_INK_RATIO,
                 search_ratio: float = SEARCH_RATIO):
        self.params = GridParams(chars_per_line, empty_ink_ratio, search_ratio)

    # ── 纯函数核心 ────────────────────────────────────────

    def segment_page(self, image: np.ndarray, layout: dict) -> dict:
        if image.ndim == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = image.shape[:2]
        n = self.params.chars_per_line

        borders = layout.get("borders", {})
        inner = borders.get("inner_frame", {})
        col_top = inner.get("top", {}).get("intercept", 0)
        col_bottom = inner.get("bottom", {}).get("intercept", h)

        columns_info = layout.get("columns", {}).get("columns", []) \
            or borders.get("columns", [])

        # 刻本文字列宽度一致：过滤版心/界行缝等窄列
        widths = [c["right_x"] - c["left_x"] for c in columns_info]
        median_w = float(np.median(widths)) if widths else 0.0

        result_columns = []
        for col in columns_info:
            left_x, right_x = float(col["left_x"]), float(col["right_x"])
            col_w = right_x - left_x
            col_result = {"index": col["index"], "left_x": left_x,
                          "right_x": right_x, "ocr_text": "", "cells": []}
            y1 = max(0, int(col_top))
            y2 = min(h, int(col_bottom))
            x1 = max(0, int(left_x) + 2)
            x2 = min(w, int(right_x) - 2)
            if col_w < median_w * MIN_COL_WIDTH_RATIO or x2 <= x1 or y2 <= y1:
                col_result["skipped"] = "non_text_column"
                result_columns.append(col_result)
                continue
            cells = segment_column(image[y1:y2, x1:x2], n, self.params)
            for c in cells:   # 局部 → 全图坐标
                c["y_top"] += y1
                c["y_bottom"] += y1
            col_result["cells"] = cells
            result_columns.append(col_result)

        return {
            "image_size": {"width": w, "height": h},
            "chars_per_line": n,
            "segmenter": "grid_strict",
            "columns": result_columns,
        }

    # ── IO 壳 ────────────────────────────────────────────

    def run_book(self, book_out_dir: Path,
                 source_dir: Path | None = None,
                 name_filter: set[str] | None = None) -> dict:
        """遍历 phase2_layout/*_layout.json → 写 phase3_char_grid/。"""
        book_out_dir = Path(book_out_dir)
        layout_dir = book_out_dir / "phase2_layout"
        layout_files = sorted(layout_dir.glob("*_layout.json"))
        if name_filter is not None:
            layout_files = [f for f in layout_files
                            if f.stem.replace("_layout", "") in name_filter]
        if not layout_files:
            raise FileNotFoundError(f"未找到 layout JSON: {layout_dir}"
                                    "（请先运行 extract --steps layout）")

        src = Path(source_dir) if source_dir \
            else CharExtractor._resolve_source_dir(book_out_dir)
        out_dir = book_out_dir / "phase3_char_grid"
        out_dir.mkdir(parents=True, exist_ok=True)

        n_pages = n_chars = n_empty = 0
        for lf in layout_files:
            stem = lf.stem.replace("_layout", "")
            img_path = CharExtractor._find_page_image(src, stem)
            if img_path is None:
                print(f"  跳过 {stem}: 找不到页面图")
                continue
            image = imread(str(img_path))
            if image is None:
                continue
            with open(lf, encoding="utf-8") as f:
                layout = json.load(f)
            result = self.segment_page(image, layout)
            with open(out_dir / f"{stem}_char_grid.json", "w",
                      encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            pc = sum(1 for c in result["columns"] for x in c["cells"]
                     if x["type"] == "char")
            pe = sum(1 for c in result["columns"] for x in c["cells"]
                     if x["type"] == "empty")
            n_chars += pc
            n_empty += pe
            n_pages += 1
            print(f"  {stem}: {pc} 字 / {pe} 空")

        meta = {"segmenter": "grid_strict",
                "params": {"chars_per_line": self.params.chars_per_line,
                           "empty_ink_ratio": self.params.empty_ink_ratio,
                           "search_ratio": self.params.search_ratio},
                "stats": {"pages": n_pages, "chars": n_chars,
                          "empty": n_empty}}
        with open(out_dir / "grid_meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return meta
