"""表格检测与 Cell OCR 识别模块。

流程：
1. 形态学检测水平/垂直表格线 → 构建网格
2. 擦除表格线 → 单 cell 裁切 → 2x 放大 + 白边
3. PaddleOCR 逐 cell 识别 → 噪声过滤
4. 输出结构化 JSON（格式见 .claude/doc/table_cell_format.md）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import cv2
import numpy as np


# ──────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────

@dataclass
class CellChar:
    """单字识别结果。"""
    char: str
    bbox: list[int]       # [x1, y1, x2, y2] 相对原图
    confidence: float


@dataclass
class TableCell:
    """表格单元格。"""
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    bbox: list[int] = field(default_factory=list)   # [x1, y1, x2, y2]
    size: list[int] = field(default_factory=list)    # [w, h]
    text: str = ""
    confidence: float = 0.0
    char_count: int = 0
    chars: list[CellChar] = field(default_factory=list)


@dataclass
class TableGrid:
    """表格网格结构。"""
    rows: int
    cols: int
    h_lines: list[int]    # rows+1 条水平线 y 坐标
    v_lines: list[int]    # cols+1 条垂直线 x 坐标


@dataclass
class TableResult:
    """表格识别完整结果。"""
    image_path: str
    image_size: list[int]   # [w, h]
    grid: TableGrid
    cells: list[TableCell]

    def to_dict(self) -> dict:
        """转为可序列化的 dict。"""
        return {
            "image": self.image_path,
            "image_size": self.image_size,
            "table": {
                "rows": self.grid.rows,
                "cols": self.grid.cols,
                "h_lines": self.grid.h_lines,
                "v_lines": self.grid.v_lines,
            },
            "cells": [
                {
                    "row": c.row,
                    "col": c.col,
                    "row_span": c.row_span,
                    "col_span": c.col_span,
                    "bbox": c.bbox,
                    "size": c.size,
                    "text": c.text,
                    "confidence": round(c.confidence, 3),
                    "char_count": c.char_count,
                    "chars": [
                        {
                            "char": ch.char,
                            "bbox": ch.bbox,
                            "confidence": round(ch.confidence, 3),
                        }
                        for ch in c.chars
                    ],
                }
                for c in self.cells
                if c.text  # 只输出有内容的 cell
            ],
        }


# ──────────────────────────────────────────────
# 表格线检测
# ──────────────────────────────────────────────

def _detect_line_positions(binary: np.ndarray, axis: int,
                           kernel_ratio: int = 8,
                           min_coverage: float = 0.10,
                           min_gap: int = 25) -> list[int]:
    """从二值图中检测水平(axis=1)或垂直(axis=0)线位置。"""
    h, w = binary.shape
    if axis == 1:  # 水平线
        klen = max(w // kernel_ratio, 10)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (klen, 1))
        morph = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)
        proj = np.sum(morph, axis=1) / 255
        total = w
    else:  # 垂直线
        klen = max(h // kernel_ratio, 10)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, klen))
        morph = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)
        proj = np.sum(morph, axis=0) / 255
        total = h

    threshold = total * min_coverage
    lines: list[tuple[int, float]] = []
    in_line = False
    start = 0

    for i in range(len(proj)):
        if proj[i] > threshold:
            if not in_line:
                start = i
                in_line = True
        else:
            if in_line:
                mid = (start + i) // 2
                strength = float(np.max(proj[start:i]) / total)
                if not lines or mid - lines[-1][0] > min_gap:
                    lines.append((mid, strength))
                elif strength > lines[-1][1]:
                    lines[-1] = (mid, strength)
                in_line = False
    if in_line:
        mid = (start + len(proj)) // 2
        strength = float(np.max(proj[start:]) / total)
        if not lines or mid - lines[-1][0] > min_gap:
            lines.append((mid, strength))

    return [pos for pos, _ in lines]


def detect_table_grid(gray: np.ndarray, min_gap: int = 25) -> TableGrid | None:
    """检测表格网格，返回 TableGrid 或 None（非表格页）。"""
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    h_lines = _detect_line_positions(binary, axis=1, min_gap=min_gap)
    v_lines = _detect_line_positions(binary, axis=0, min_gap=min_gap)

    if len(h_lines) < 2 or len(v_lines) < 2:
        return None

    return TableGrid(
        rows=len(h_lines) - 1,
        cols=len(v_lines) - 1,
        h_lines=h_lines,
        v_lines=v_lines,
    )


# ──────────────────────────────────────────────
# 表格线擦除
# ──────────────────────────────────────────────

def erase_table_lines(gray: np.ndarray) -> np.ndarray:
    """擦除水平和垂直表格线，保留文字，返回灰度图。"""
    _, bin_inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h, w = bin_inv.shape

    # 水平线 mask
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 6, 10), 1))
    horiz_mask = cv2.morphologyEx(bin_inv, cv2.MORPH_OPEN, horiz_kernel, iterations=1)

    # 垂直线 mask
    vert_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h // 6, 10)))
    vert_mask = cv2.morphologyEx(bin_inv, cv2.MORPH_OPEN, vert_kernel, iterations=1)

    # 合并并膨胀覆盖边缘
    lines_mask = cv2.bitwise_or(horiz_mask, vert_mask)
    lines_mask = cv2.dilate(lines_mask, np.ones((3, 3), np.uint8), iterations=1)

    result = gray.copy()
    result[lines_mask > 0] = 255
    return result


# ──────────────────────────────────────────────
# Cell OCR
# ──────────────────────────────────────────────

# 噪声字符正则：只保留包含中文的文本
_HAS_CJK = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')

# ──────────────────────────────────────────────
# 字符后处理：映射纠正 + 字符集过滤
# ──────────────────────────────────────────────

# 常见 OCR 误识别 → 正确字符 映射
CHAR_CORRECTION_MAP: dict[str, str] = {
    # 宫 的常见误识别
    "营": "宫", "管": "宫", "掌": "宫", "常": "宫",
    "富": "宫", "量": "宫", "京": "宫", "答": "宫",
    # 日 的误识别
    "王": "日",
    # 古籍草书/异体字误识别
    "青": "七",
    "夏": "八",
    "草": "半",
}

# 按行类型定义的允许字符集
YEAR_CHARS = frozenset("一二三四五六七八九十百千年")
WEEKDAY_CHARS = frozenset("一二三四五六七月日金木水火土大小")
ASTRO_CHARS = frozenset("一二三四五六七八九十初宫度分秒半壹")


def _correct_char(ch: str) -> str:
    """对单个字符做映射纠正。"""
    return CHAR_CORRECTION_MAP.get(ch, ch)


def _filter_text(text: str, allowed_chars: frozenset | None) -> str:
    """映射纠正 + 字符集过滤。"""
    corrected = "".join(_correct_char(c) for c in text)
    if allowed_chars is None:
        return corrected
    return "".join(c for c in corrected if c in allowed_chars)


def _ocr_single_cell(ocr, cell_img: np.ndarray, scale: float = 2.0,
                      padding: int = 15, min_conf: float = 0.15,
                      cell_origin: tuple[int, int] = (0, 0),
                      allowed_chars: frozenset | None = None):
    """对单个 cell 图像做 OCR，返回 (text, confidence, chars)。

    Args:
        ocr: PaddleOCR 实例
        cell_img: cell 裁切图（灰度或 BGR）
        scale: 放大倍数
        padding: 白边像素
        min_conf: 最低置信度阈值
        cell_origin: cell 左上角在原图中的 (x, y) 坐标
        allowed_chars: 允许的字符集，None 则不过滤
    """
    h, w = cell_img.shape[:2]
    new_w, new_h = int(w * scale), int(h * scale)
    scaled = cv2.resize(cell_img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    padded = cv2.copyMakeBorder(scaled, padding, padding, padding, padding,
                                 cv2.BORDER_CONSTANT, value=255 if len(scaled.shape) == 2 else (255, 255, 255))
    if len(padded.shape) == 2:
        padded = cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)

    results = list(ocr.predict(padded, return_word_box=True))

    chars: list[CellChar] = []
    for res in results:
        data = res.json
        if "res" not in data:
            continue

        text_words = data["res"].get("text_word", [])
        word_boxes = data["res"].get("text_word_boxes", [])
        rec_scores = data["res"].get("rec_scores", [])

        for line_idx in range(len(text_words)):
            line_chars = text_words[line_idx]
            line_boxes = word_boxes[line_idx] if line_idx < len(word_boxes) else []
            line_score = rec_scores[line_idx] if line_idx < len(rec_scores) else 0.0

            # 跳过低置信度行
            if line_score < min_conf:
                continue

            for j, ch in enumerate(line_chars):
                if j >= len(line_boxes):
                    break

                # 映射纠正
                corrected = _correct_char(ch)

                # 字符集过滤
                if allowed_chars is not None:
                    if corrected not in allowed_chars:
                        continue
                elif not _HAS_CJK.search(corrected):
                    # 无字符集限制时，至少过滤非中文
                    continue

                box = line_boxes[j]
                # 坐标从放大+padding 空间转回原图空间
                ox = cell_origin[0]
                oy = cell_origin[1]
                x1 = int((box[0] - padding) / scale) + ox
                y1 = int((box[1] - padding) / scale) + oy
                x2 = int((box[2] - padding) / scale) + ox
                y2 = int((box[3] - padding) / scale) + oy

                chars.append(CellChar(
                    char=corrected,
                    bbox=[x1, y1, x2, y2],
                    confidence=float(line_score),
                ))

    # 按 y 坐标排序（竖排文字从上到下）
    chars.sort(key=lambda c: (c.bbox[1] + c.bbox[3]) / 2)

    text = "".join(c.char for c in chars)
    avg_conf = sum(c.confidence for c in chars) / len(chars) if chars else 0.0

    return text, avg_conf, chars


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

class TableDetector:
    """表格检测与识别。

    使用方法：
        detector = TableDetector()
        result = detector.detect("path/to/image.png")
        data = result.to_dict()

    自定义 OCR 配置：
        detector = TableDetector(ocr_config={"lang": "ch", "device": "cpu"})
    """

    # 默认 PaddleOCR 参数
    DEFAULT_OCR_CONFIG = {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "lang": "chinese_cht",
        "text_det_thresh": 0.3,
        "text_det_box_thresh": 0.5,
        "device": "gpu",
    }

    def __init__(self, scale: float = 2.0, min_conf: float = 0.15,
                 erase_lines: bool = True,
                 row_charsets: dict[int, frozenset] | None = None,
                 ocr_config: dict | None = None):
        """
        Args:
            scale: cell 放大倍数
            min_conf: 最低置信度阈值
            erase_lines: 是否擦除表格线
            row_charsets: 按行索引指定允许字符集，如 {0: YEAR_CHARS, 1: WEEKDAY_CHARS}
                         未指定的行使用默认 CJK 过滤
            ocr_config: PaddleOCR 构造参数覆盖，如 {"lang": "ch", "device": "cpu"}
        """
        self._ocr = None
        self.scale = scale
        self.min_conf = min_conf
        self.erase_lines = erase_lines
        self.row_charsets = row_charsets or {}
        self.ocr_config = {**self.DEFAULT_OCR_CONFIG, **(ocr_config or {})}

    def _ensure_ocr(self):
        if self._ocr is not None:
            return
        import os, sys
        if sys.platform == "win32":
            import site as _site
            for sp_dir in _site.getsitepackages():
                nv = os.path.join(sp_dir, "nvidia")
                if os.path.isdir(nv):
                    for sub in os.listdir(nv):
                        for d in ("bin", "lib"):
                            dp = os.path.join(nv, sub, d)
                            if os.path.isdir(dp):
                                os.add_dll_directory(dp)
                    break
        from paddleocr import PaddleOCR
        self._ocr = PaddleOCR(**self.ocr_config)

    def detect(self, image_path: str) -> TableResult | None:
        """检测表格并识别所有 cell 内容。

        Returns:
            TableResult 或 None（非表格页）
        """
        img = cv2.imread(image_path)
        if img is None:
            raise FileNotFoundError(f"无法读取图像: {image_path}")

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # 1. 检测网格
        grid = detect_table_grid(gray)
        if grid is None:
            return None

        # 2. 擦除表格线
        if self.erase_lines:
            gray_clean = erase_table_lines(gray)
        else:
            gray_clean = gray

        # 3. 初始化 OCR
        self._ensure_ocr()

        # 4. 逐 cell OCR
        margin = 3  # 内缩避开线条残留
        cells: list[TableCell] = []

        for r in range(grid.rows):
            for c in range(grid.cols):
                x1 = grid.v_lines[c]
                y1 = grid.h_lines[r]
                x2 = grid.v_lines[c + 1]
                y2 = grid.h_lines[r + 1]

                # 裁切 cell
                cy1 = min(y1 + margin, y2)
                cy2 = max(y2 - margin, y1)
                cx1 = min(x1 + margin, x2)
                cx2 = max(x2 - margin, x1)

                if cy2 <= cy1 or cx2 <= cx1:
                    continue

                cell_img = gray_clean[cy1:cy2, cx1:cx2]

                # 按行索引查找字符集
                allowed = self.row_charsets.get(r)

                text, conf, chars = _ocr_single_cell(
                    self._ocr, cell_img,
                    scale=self.scale,
                    min_conf=self.min_conf,
                    cell_origin=(cx1, cy1),
                    allowed_chars=allowed,
                )

                cells.append(TableCell(
                    row=r,
                    col=c,
                    bbox=[x1, y1, x2, y2],
                    size=[x2 - x1, y2 - y1],
                    text=text,
                    confidence=conf,
                    char_count=len(chars),
                    chars=chars,
                ))

        return TableResult(
            image_path=image_path,
            image_size=[w, h],
            grid=grid,
            cells=cells,
        )

    def detect_and_visualize(self, image_path: str, output_path: str) -> TableResult | None:
        """检测表格并保存可视化 debug 图。"""
        result = self.detect(image_path)
        if result is None:
            return None

        img = cv2.imread(image_path)
        grid = result.grid

        # 画网格线
        h, w = img.shape[:2]
        for y in grid.h_lines:
            cv2.line(img, (0, y), (w, y), (0, 0, 255), 1)
        for x in grid.v_lines:
            cv2.line(img, (x, 0), (x, h), (255, 0, 0), 1)

        # 标注 cell 文本
        for cell in result.cells:
            if not cell.text:
                continue
            x1, y1 = cell.bbox[0], cell.bbox[1]
            cv2.putText(img, f"[{cell.row},{cell.col}]",
                        (x1 + 2, y1 + 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 180, 0), 1)

        cv2.imwrite(output_path, img)
        return result
