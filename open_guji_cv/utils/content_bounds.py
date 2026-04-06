"""内容区域边界检测 — 裁到正文区。

四方向裁切：
- 左右：LSD 检测垂直线段 → 聚类 → 找外框线位置
- 上下：从外框线向内找正文界栏线，裁掉天头/地脚

不依赖 deskew 是否已裁切 — 两种情况都能正确处理。
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

# 导入 border_detect 的聚类函数
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from border_detect import cluster_lines, _find_border_pair


# ── 上下方向：正文界栏线检测 ──
INNER_LINE_EDGE_RATIO = 0.15
INNER_LINE_SEARCH_MAX_TOP = 0.25    # 天头最大深度（天头较大，~16%）
INNER_LINE_SEARCH_MAX_BOTTOM = 0.10 # 地脚最大深度（地脚较小，~6%）
INNER_LINE_GAP_MIN = 30
INNER_LINE_PADDING = 3

# ── LSD 参数 ──
_MIN_LINE_LENGTH = 30
_ANGLE_TOL = 10.0


def find_content_bounds(gray: np.ndarray) -> tuple[int, int, int, int]:
    """找到正文内容区的边界。

    Returns:
        (top, bottom, left, right) 像素坐标
    """
    h, w = gray.shape
    gray_u8 = gray.astype(np.uint8) if gray.dtype != np.uint8 else gray

    # ── 左右：LSD + 聚类找外框线 ──
    left, right = _find_lr_by_lsd(gray_u8, h, w)

    # ── 上下：外框线 + 正文界栏线 ──
    edges = cv2.Canny(gray_u8, 30, 100, apertureSize=3)
    content_w = right - left + 1

    # 先找水平外框线
    top_frame = _find_h_frame(edges, h, left, right, content_w, from_top=True)
    bottom_frame = _find_h_frame(edges, h, left, right, content_w, from_top=False)

    # 从外框线向内找正文界栏线
    top = _find_inner_line(edges, top_frame, h, left, right, content_w, from_top=True)
    bottom = _find_inner_line(edges, bottom_frame, h, left, right, content_w, from_top=False)

    return top, bottom, left, right


# ─── 左右方向：LSD + border_detect ────────────────────────


def _find_lr_by_lsd(gray: np.ndarray, h: int, w: int) -> tuple[int, int]:
    """用 LSD 检测垂直线段，聚类后找左右外框线。"""
    lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    raw_lines, widths, _, _ = lsd.detect(gray)

    if raw_lines is None:
        return 0, w - 1

    v_segs = []
    for i, line in enumerate(raw_lines):
        x1, y1, x2, y2 = line[0]
        dx, dy = x2 - x1, y2 - y1
        length = np.sqrt(dx * dx + dy * dy)
        if length < _MIN_LINE_LENGTH:
            continue
        wd = float(widths[i][0]) if widths is not None else 1.0
        angle = abs(np.degrees(np.arctan2(abs(dx), abs(dy))))
        if angle <= _ANGLE_TOL:
            v_segs.append({
                "x1": float(x1), "y1": float(y1),
                "x2": float(x2), "y2": float(y2),
                "length": float(length), "width": wd, "type": "vertical",
            })

    if len(v_segs) < 2:
        return 0, w - 1

    v_clusters = cluster_lines(v_segs, "v", pos_tol=15, max_gap=60)

    left_pair = _find_border_pair(v_clusters, "min", h, w)
    right_pair = _find_border_pair(v_clusters, "max", h, w)

    left = int(left_pair["outer"]["intercept"]) if left_pair["outer"] else 0
    right = int(right_pair["outer"]["intercept"]) if right_pair["outer"] else w - 1

    # 安全检查：content 至少 50% 宽度
    if right - left < w * 0.5:
        return 0, w - 1

    return max(0, left), min(w - 1, right)


# ─── 上下方向：水平外框线 + 正文界栏线 ─────────────────────


def _find_h_frame(
    edges: np.ndarray,
    h: int, col_left: int, col_right: int,
    content_w: int,
    from_top: bool,
) -> int:
    """找水平外框线（上/下边缘最近的强水平边缘行）。"""
    search_depth = int(h * 0.10)

    if from_top:
        for r in range(min(search_depth, h)):
            d = np.sum(edges[r, col_left:col_right + 1] > 0) / content_w
            if d >= 0.20:
                return r
        return 0
    else:
        for r in range(h - 1, max(h - search_depth, -1), -1):
            d = np.sum(edges[r, col_left:col_right + 1] > 0) / content_w
            if d >= 0.20:
                return r
        return h - 1


def _find_inner_line(
    edges: np.ndarray,
    frame_line: int,
    h: int,
    col_left: int, col_right: int,
    content_w: int,
    from_top: bool,
) -> int:
    """从外框线向内找正文界栏线。

    天头较大（~16% 高度），搜索范围宽。
    地脚较小（~6% 高度），搜索范围窄，避免把版心鱼尾横线
    （距外框线 ~31%）误认为界栏线。
    """
    if from_top:
        search_max = int(h * INNER_LINE_SEARCH_MAX_TOP)
        scan_start = frame_line + INNER_LINE_GAP_MIN
        scan_end = min(h, frame_line + search_max)
        for r in range(scan_start, scan_end):
            d = np.sum(edges[r, col_left:col_right + 1] > 0) / content_w
            if d >= INNER_LINE_EDGE_RATIO:
                return max(0, r - INNER_LINE_PADDING)
        return frame_line

    else:
        search_max = int(h * INNER_LINE_SEARCH_MAX_BOTTOM)
        scan_start = frame_line - INNER_LINE_GAP_MIN
        scan_end = max(0, frame_line - search_max)
        for r in range(scan_start, scan_end, -1):
            d = np.sum(edges[r, col_left:col_right + 1] > 0) / content_w
            if d >= INNER_LINE_EDGE_RATIO:
                return min(h - 1, r + INNER_LINE_PADDING)
        return frame_line
