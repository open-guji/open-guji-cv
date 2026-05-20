"""长直线增强预处理器。

检测图像中的长直线（边框线、界行线），整条复原。
只增强覆盖率高的长线，不影响文字笔画。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

from .base import BasePreprocessor

# 导入 border_detect 的共线性聚类
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from border_detect import cluster_lines

if TYPE_CHECKING:
    from ..profile import BookProfile


class EnhanceLinesPreprocessor(BasePreprocessor):
    """长直线增强：找到长直线后整条复原。

    只增强覆盖率 >= MIN_COVERAGE 的长直线（边框线、界行线），
    不触碰文字笔画中的短线段。
    区分外边框（较粗）和内界行（较细）分别处理。
    """

    name = "enhance_lines"
    priority = 25

    # LSD 参数
    _MIN_LINE_LENGTH = 30
    _ANGLE_TOL = 10.0

    # 聚类参数
    _POS_TOL = 15
    _MAX_GAP = 60

    # 增强参数
    MIN_COVERAGE = 0.5       # 最小覆盖率
    SCAN_MARGIN = 10         # 法线方向最大搜索范围（像素）—— 减小以避免碰到文字
    WIDTH_CAP = 15           # 单次线宽测量上限（排除文字干扰）

    @classmethod
    def is_needed(cls, profile: BookProfile) -> bool:
        return True

    def process(self, image: np.ndarray, profile: BookProfile) -> np.ndarray:
        gray = (cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                if len(image.shape) == 3 else image)
        h, w = gray.shape

        # Otsu 二值化：0=前景(线条), 255=背景
        _, binary = cv2.threshold(gray, 0, 255,
                                  cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary) < 127:
            binary = cv2.bitwise_not(binary)

        # 1. LSD 检测 + 分类
        lsd_lines = self._detect_lsd_lines(gray)
        if not lsd_lines:
            return image

        h_lines = [ln for ln in lsd_lines if ln["type"] == "horizontal"]
        v_lines = [ln for ln in lsd_lines if ln["type"] == "vertical"]

        # 2. 共线性聚类
        h_clusters = cluster_lines(h_lines, "h", self._POS_TOL, self._MAX_GAP)
        v_clusters = cluster_lines(v_lines, "v", self._POS_TOL, self._MAX_GAP)

        # 3. 筛选长线
        long_h = [c for c in h_clusters
                  if c["total_length"] >= w * self.MIN_COVERAGE]
        long_v = [c for c in v_clusters
                  if c["total_length"] >= h * self.MIN_COVERAGE]

        if not long_h and not long_v:
            return image

        # 4. 测量线条颜色
        line_color = self._estimate_line_color(gray, binary)

        # 5. 创建增强掩码（255=不改，line_color=需要填充）
        mask = np.full_like(gray, 255, dtype=np.uint8)

        # 6. 对每条长线：测量实际线宽，然后整条复原
        for cluster in long_h:
            self._restore_full_line(binary, mask, cluster, "h",
                                    w, h, line_color)
        for cluster in long_v:
            self._restore_full_line(binary, mask, cluster, "v",
                                    w, h, line_color)

        # 7. 合成：取原图和掩码中更暗的像素（只加粗不变细）
        if len(image.shape) == 3:
            mask_3ch = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
            result = np.minimum(image, mask_3ch)
        else:
            result = np.minimum(image, mask)

        return result

    # ─── LSD 检测 ─────────────────────────────────────────────

    def _detect_lsd_lines(self, gray: np.ndarray) -> list[dict]:
        """LSD 检测线段并分类为水平/垂直。"""
        lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
        raw_lines, widths, _, _ = lsd.detect(gray)

        if raw_lines is None:
            return []

        result = []
        for i, line in enumerate(raw_lines):
            x1, y1, x2, y2 = line[0]
            dx = x2 - x1
            dy = y2 - y1
            length = np.sqrt(dx * dx + dy * dy)

            if length < self._MIN_LINE_LENGTH:
                continue

            width = float(widths[i][0]) if widths is not None else 1.0
            angle_from_vert = abs(np.degrees(np.arctan2(abs(dx), abs(dy))))

            if angle_from_vert <= self._ANGLE_TOL:
                line_type = "vertical"
            elif angle_from_vert >= (90 - self._ANGLE_TOL):
                line_type = "horizontal"
            else:
                continue

            result.append({
                "x1": float(x1), "y1": float(y1),
                "x2": float(x2), "y2": float(y2),
                "length": float(length),
                "width": width,
                "type": line_type,
            })

        return result

    # ─── 线条颜色估计 ─────────────────────────────────────────

    @staticmethod
    def _estimate_line_color(gray: np.ndarray,
                             binary: np.ndarray) -> int:
        """估计线条的灰度值（取前景像素的中位数）。"""
        fg_pixels = gray[binary == 0]
        if len(fg_pixels) == 0:
            return 0
        return int(np.median(fg_pixels))

    # ─── 整条复原 ─────────────────────────────────────────────

    def _restore_full_line(self, binary: np.ndarray, mask: np.ndarray,
                           cluster: dict, axis: str,
                           img_w: int, img_h: int,
                           line_color: int) -> None:
        """整条复原一条长直线。

        1. 沿拟合直线采样，测量实际线宽（排除异常值）
        2. 取稳健的目标线宽（中位数）
        3. 沿拟合直线全程绘制该宽度的线
        """
        slope = cluster["slope"]
        intercept = cluster["intercept"]
        span = img_w if axis == "h" else img_h
        cross_dim = img_h if axis == "h" else img_w

        # 全程坐标
        coords = np.arange(span)
        centers = slope * coords + intercept

        # 测量实际线宽（用于确定目标宽度）
        center_ints = np.rint(centers).astype(np.int32)
        measured = self._measure_widths_robust(
            binary, coords, center_ints, axis, cross_dim)

        # 取有效测量的中位线宽
        valid = measured[(measured > 0) & (measured <= self.WIDTH_CAP)]
        if len(valid) == 0:
            # 没有合理的测量，用 LSD 报告的平均宽度
            target_width = max(int(round(cluster["avg_width"])), 2)
        else:
            target_width = max(int(np.median(valid)), 2)

        half_w = target_width / 2.0

        # 整条画线：沿拟合直线全程绘制
        self._draw_full_line(mask, coords, centers, axis,
                             half_w, line_color, cross_dim)

    def _measure_widths_robust(self, binary: np.ndarray,
                               coords: np.ndarray,
                               center_ints: np.ndarray,
                               axis: str,
                               cross_dim: int) -> np.ndarray:
        """稳健的线宽测量。

        只在拟合中心附近很小范围内搜索，避免碰到文字。
        超过 WIDTH_CAP 的测量视为异常（碰到了文字笔画）。
        """
        span = len(coords)
        result = np.zeros(span, dtype=np.int32)
        img_h, img_w = binary.shape
        margin = self.SCAN_MARGIN

        for i in range(span):
            coord = int(coords[i])
            c_int = int(center_ints[i])

            if c_int < 0 or c_int >= cross_dim:
                continue

            if axis == "h":
                if coord < 0 or coord >= img_w:
                    continue
                col = binary[:, coord]
            else:
                if coord < 0 or coord >= img_h:
                    continue
                col = binary[coord, :]

            y_center = c_int
            col_len = len(col)

            if y_center < 0 or y_center >= col_len:
                continue

            if col[y_center] != 0:
                # 中心不是黑色，在小范围内搜索
                found = False
                for offset in range(1, margin + 1):
                    for sign in (-1, 1):
                        pos = y_center + sign * offset
                        if 0 <= pos < col_len and col[pos] == 0:
                            y_center = pos
                            found = True
                            break
                    if found:
                        break
                if not found:
                    continue

            # 从 y_center 向两侧扩展（但限制在 margin 范围内）
            lo = y_center
            while lo > 0 and col[lo - 1] == 0 and y_center - lo < margin:
                lo -= 1
            hi = y_center
            while hi < col_len - 1 and col[hi + 1] == 0 and hi - y_center < margin:
                hi += 1

            width = hi - lo + 1
            result[i] = width

        return result

    @staticmethod
    def _draw_full_line(mask: np.ndarray,
                        coords: np.ndarray,
                        centers: np.ndarray,
                        axis: str, half_width: float,
                        color: int, cross_dim: int) -> None:
        """沿拟合直线全程绘制，整条复原。"""
        img_h, img_w = mask.shape
        lo_arr = np.clip(np.rint(centers - half_width).astype(np.int32),
                         0, cross_dim - 1)
        hi_arr = np.clip(np.rint(centers + half_width).astype(np.int32),
                         0, cross_dim - 1)

        for i in range(len(coords)):
            coord = int(coords[i])
            lo = int(lo_arr[i])
            hi = int(hi_arr[i])
            if lo > hi:
                continue

            if axis == "h":
                if 0 <= coord < img_w:
                    slc = mask[lo:hi + 1, coord]
                    np.minimum(slc, color, out=slc)
            else:
                if 0 <= coord < img_h:
                    slc = mask[coord, lo:hi + 1]
                    np.minimum(slc, color, out=slc)
