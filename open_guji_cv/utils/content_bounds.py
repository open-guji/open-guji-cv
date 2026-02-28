"""内容区域边界检测：利用行/列标准差定位边框外缘。

供 crop_margin（裁边框）和 crop_spine（裁书脊）共用。
"""

from __future__ import annotations

import numpy as np


# ── 参数 ──
THRESHOLD_RATIO = 0.25      # 标准差阈值 = content_std × 此系数
MIN_STD_THRESHOLD = 8.0     # 绝对最小标准差阈值
PADDING = 3                 # 边界向外扩展像素数（保护边框）


def find_content_bounds(gray: np.ndarray) -> tuple[int, int, int, int]:
    """利用行/列标准差找到内容区域（边框外缘）的边界。

    算法：纯色背景（白/黑）标准差≈0，内容区（文字+边框）标准差高。
    两遍扫描：先列标准差定左右，再在内容列内行标准差定上下。

    Args:
        gray: 灰度图（uint8 或 float）

    Returns:
        (top, bottom, left, right) 像素坐标（含 padding）
    """
    h, w = gray.shape
    gray_f = gray.astype(np.float32)

    # Pass 1: 列标准差 → 左右边界
    col_stds = np.std(gray_f, axis=0)
    left, right = _find_bounds(col_stds, w)

    # Pass 2: 行标准差（仅在内容列范围内）→ 上下边界
    content_region = gray_f[:, left:right + 1]
    row_stds = np.std(content_region, axis=1)
    top, bottom = _find_bounds(row_stds, h)

    return top, bottom, left, right


def _find_bounds(stds: np.ndarray, length: int) -> tuple[int, int]:
    """从标准差序列中找到内容区域的起止位置。"""
    # 自适应阈值：取中间 1/3 区域的标准差中位数作为"内容区"基线
    mid_s = length // 3
    mid_e = 2 * length // 3
    content_std = np.median(stds[mid_s:mid_e])
    threshold = max(content_std * THRESHOLD_RATIO, MIN_STD_THRESHOLD)

    # 平滑以减少噪声
    win = max(3, length // 200)
    smoothed = np.convolve(stds, np.ones(win) / win, mode='same')

    # 从两端向内扫描
    start = 0
    for i in range(length):
        if smoothed[i] > threshold:
            start = i
            break

    end = length - 1
    for i in range(length - 1, -1, -1):
        if smoothed[i] > threshold:
            end = i
            break

    # 向外扩展 padding
    start = max(0, start - PADDING)
    end = min(length - 1, end + PADDING)

    return start, end
