"""M3 两两配准验证 —— 保守聚类的核心判据（设计文档 6.3）。

在 ±max_shift 平移 × 少量缩放的小网格上搜索最优对齐，
相似度 = 墨迹像素 F1（2·|A∩B| / (|A|+|B|)）。

三档判决：
- same:   f1 ≥ theta_high 且局部差异块不超限
- unsure: theta_low ≤ f1 < theta_high，或整体相似但存在集中的局部差异
          （"曰/日"一笔之差的防线）—— 不合并，供审查/标定
- diff:   f1 < theta_low
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

THETA_HIGH = 0.80
THETA_LOW = 0.62
MAX_SHIFT = 3
SCALES = (0.95, 1.0, 1.05)
DIFF_BLOB_RATIO = 0.06

_KERNEL3 = np.ones((3, 3), dtype=np.uint8)


@dataclass
class PairVerdict:
    verdict: str            # "same" | "unsure" | "diff"
    f1: float               # 最优对齐下的墨迹 F1
    dilated_f1: float       # 双方膨胀 1px 后的 F1（磨损容忍度参考）
    shift: tuple[int, int]  # 最优 (dx, dy)
    scale: float            # 最优缩放
    diff_blob_ratio: float  # 最大局部差异块面积 / 平均墨迹面积


def _rescale(binary: np.ndarray, scale: float) -> np.ndarray:
    """围绕图心等比缩放，输出尺寸不变（裁切/补零）。"""
    if scale == 1.0:
        return binary
    size = binary.shape[0]
    n = max(1, int(round(size * scale)))
    resized = cv2.resize(binary * 255, (n, n), interpolation=cv2.INTER_AREA)
    resized = (resized > 127).astype(np.uint8)
    out = np.zeros_like(binary)
    if n >= size:
        off = (n - size) // 2
        out[:, :] = resized[off:off + size, off:off + size]
    else:
        off = (size - n) // 2
        out[off:off + n, off:off + n] = resized
    return out


def _shifted_view(padded: np.ndarray, dx: int, dy: int, size: int,
                  max_shift: int) -> np.ndarray:
    """从 pad 过的图上取平移 (dx, dy) 后的 size×size 视图。"""
    return padded[max_shift + dy:max_shift + dy + size,
                  max_shift + dx:max_shift + dx + size]


def _f1(a: np.ndarray, b: np.ndarray, na: int, nb: int) -> float:
    if na == 0 or nb == 0:
        return 0.0
    inter = int(np.count_nonzero(a & b))
    return 2.0 * inter / (na + nb)


def _largest_diff_blob(a: np.ndarray, b_aligned: np.ndarray) -> int:
    """单侧差异（互相膨胀 1px 后仍不重叠的部分）的最大连通块面积。

    膨胀容忍 1px 配准/笔画粗细误差，剩下的才是"缺一笔/多一笔"式的真实差异。
    """
    a_d = cv2.dilate(a, _KERNEL3)
    b_d = cv2.dilate(b_aligned, _KERNEL3)
    diff = ((a & (1 - b_d)) | (b_aligned & (1 - a_d))).astype(np.uint8)
    if not diff.any():
        return 0
    n, _, stats, _ = cv2.connectedComponentsWithStats(diff, connectivity=8)
    return int(stats[1:, cv2.CC_STAT_AREA].max()) if n > 1 else 0


def verify_pair(a: np.ndarray, b: np.ndarray,
                max_shift: int = MAX_SHIFT,
                scales: tuple[float, ...] = SCALES,
                theta_high: float = THETA_HIGH,
                theta_low: float = THETA_LOW,
                diff_blob_ratio: float = DIFF_BLOB_RATIO) -> PairVerdict:
    """a, b: S×S uint8 {0,1} 归一二值图。"""
    size = a.shape[0]
    na = int(np.count_nonzero(a))

    best_f1, best_shift, best_scale = 0.0, (0, 0), 1.0
    best_b: np.ndarray | None = None

    for scale in scales:
        b_s = _rescale(b, scale)
        nb = int(np.count_nonzero(b_s))
        padded = np.zeros((size + 2 * max_shift, size + 2 * max_shift), dtype=np.uint8)
        padded[max_shift:max_shift + size, max_shift:max_shift + size] = b_s
        for dy in range(-max_shift, max_shift + 1):
            for dx in range(-max_shift, max_shift + 1):
                view = _shifted_view(padded, dx, dy, size, max_shift)
                f1 = _f1(a, view, na, nb)
                if f1 > best_f1:
                    best_f1, best_shift, best_scale = f1, (dx, dy), scale
                    best_b = view.copy()

    if best_b is None:  # 双方或一方无墨迹
        return PairVerdict("diff", 0.0, 0.0, (0, 0), 1.0, 0.0)

    nb_best = int(np.count_nonzero(best_b))
    a_d = cv2.dilate(a, _KERNEL3)
    b_d = cv2.dilate(best_b, _KERNEL3)
    dilated_f1 = _f1(a_d, b_d, int(np.count_nonzero(a_d)), int(np.count_nonzero(b_d)))

    ink_area = max(1.0, (na + nb_best) / 2.0)
    blob_ratio = _largest_diff_blob(a, best_b) / ink_area

    if best_f1 >= theta_high:
        # 形近字防线：整体够像但差异集中在一处 → 降级 unsure
        verdict = "unsure" if blob_ratio > diff_blob_ratio else "same"
    elif best_f1 >= theta_low:
        verdict = "unsure"
    else:
        verdict = "diff"

    return PairVerdict(verdict, float(best_f1), float(dilated_f1),
                       best_shift, best_scale, float(blob_ratio))
