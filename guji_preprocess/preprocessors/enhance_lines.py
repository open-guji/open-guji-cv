"""长直线增强预处理器。

检测图像中的长直线（边框线、界行线），补全断续、统一线宽。
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
    """长直线增强：断续补全 + 线宽统一。

    只增强覆盖率 >= MIN_COVERAGE 的长直线（边框线、界行线），
    不触碰文字笔画中的短线段。
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
    WIDTH_THIN_RATIO = 0.7   # 低于目标宽度的 70% 视为过细
    SCAN_MARGIN = 20         # 法线方向最大搜索范围（像素）

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
        # 确保线条是 0（黑色），背景是 255（白色）
        # 如果均值 > 127，说明多数像素是白色背景，Otsu 结果正确
        # 否则需要反转
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

        # 4. 测量线条颜色（取线段覆盖区域的中位灰度值）
        line_color = self._estimate_line_color(gray, binary)

        # 5. 创建增强掩码（255=不改，line_color=需要填充）
        mask = np.full_like(gray, 255, dtype=np.uint8)

        # 6. 对每条长线增强
        for cluster in long_h:
            self._enhance_line(binary, mask, cluster, "h", w, h, line_color)
        for cluster in long_v:
            self._enhance_line(binary, mask, cluster, "v", w, h, line_color)

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

    # ─── 单条线增强 ───────────────────────────────────────────

    def _enhance_line(self, binary: np.ndarray, mask: np.ndarray,
                      cluster: dict, axis: str,
                      img_w: int, img_h: int,
                      line_color: int) -> None:
        """增强一条长线：批量扫描线宽 → 补全 gap → 统一粗细。"""
        slope = cluster["slope"]
        intercept = cluster["intercept"]
        span = img_w if axis == "h" else img_h
        cross_dim = img_h if axis == "h" else img_w
        margin = self.SCAN_MARGIN

        # 向量化计算所有位置的中心坐标
        coords = np.arange(span)
        centers = slope * coords + intercept
        center_ints = np.rint(centers).astype(np.int32)

        # 批量扫描线宽
        measured_widths = self._measure_widths_batch(
            binary, coords, center_ints, axis, cross_dim, margin)

        # 计算目标线宽
        covered = measured_widths[measured_widths > 0]
        if len(covered) == 0:
            return
        target_width = max(int(np.median(covered)), 1)
        half_w = target_width / 2.0
        thin_threshold = target_width * self.WIDTH_THIN_RATIO

        # 找出需要增强的位置（gap 或过细）
        need_enhance = (measured_widths == 0) | (
            (measured_widths > 0) & (measured_widths < thin_threshold))
        enhance_coords = coords[need_enhance]
        enhance_centers = centers[need_enhance]

        if len(enhance_coords) == 0:
            return

        # 批量绘制增强掩码
        self._draw_line_strip(mask, enhance_coords, enhance_centers,
                              axis, half_w, line_color, cross_dim)

    def _measure_widths_batch(self, binary: np.ndarray,
                              coords: np.ndarray,
                              center_ints: np.ndarray,
                              axis: str, cross_dim: int,
                              margin: int) -> np.ndarray:
        """批量测量每个主轴坐标处的线宽。

        binary: 0=前景(线条), 255=背景
        返回 int32 数组，每个元素是对应位置的线宽。
        """
        span = len(coords)
        result = np.zeros(span, dtype=np.int32)
        img_h, img_w = binary.shape

        for i in range(span):
            coord = int(coords[i])
            c_int = int(center_ints[i])

            # 边界检查
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

            # 检查中心是否是前景
            if y_center < 0 or y_center >= col_len:
                continue

            if col[y_center] != 0:
                # 中心不是黑色，向附近搜索最近的黑色像素
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

            # 从 y_center 向两侧扩展
            lo = y_center
            while lo > 0 and col[lo - 1] == 0 and y_center - lo < margin:
                lo -= 1
            hi = y_center
            while hi < col_len - 1 and col[hi + 1] == 0 and hi - y_center < margin:
                hi += 1

            result[i] = hi - lo + 1

        return result

    @staticmethod
    def _draw_line_strip(mask: np.ndarray,
                         coords: np.ndarray,
                         centers: np.ndarray,
                         axis: str, half_width: float,
                         color: int, cross_dim: int) -> None:
        """批量在 mask 上绘制一系列横截面。"""
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
                    # mask[lo:hi+1, coord] = min(existing, color)
                    slc = mask[lo:hi + 1, coord]
                    np.minimum(slc, color, out=slc)
            else:
                if 0 <= coord < img_h:
                    slc = mask[coord, lo:hi + 1]
                    np.minimum(slc, color, out=slc)
