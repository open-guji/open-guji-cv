"""倾斜/透视校正预处理器。

优先使用透视校正（检测边框四角 → 映射为矩形），
当边框检测失败时回退到投影法旋转。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

from .base import BasePreprocessor

# 导入 border_detect 的核心函数
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from border_detect import cluster_lines, _find_border_pair, _intersect_hv

if TYPE_CHECKING:
    from ..profile import BookProfile


class NormalizePreprocessor(BasePreprocessor):
    """倾斜/透视校正。

    两种模式：
    1. 透视校正（首选）：LSD 检测边框线 → 四角交点 → getPerspectiveTransform
    2. 投影法旋转（回退）：当边框检测失败时，用投影法找最佳旋转角度
    """

    name = "normalize"
    priority = 60

    MAX_CORRECTION_ANGLE = 5.0
    MIN_CORRECTION_ANGLE = 0.1

    # 投影法参数
    _SEARCH_RANGE = 3.0
    _COARSE_STEP = 0.1
    _FINE_RANGE = 0.2
    _FINE_STEP = 0.02

    # LSD 线段参数
    _MIN_LINE_LENGTH = 30
    _ANGLE_TOL = 10.0

    @classmethod
    def is_needed(cls, profile: BookProfile) -> bool:
        return True

    def process(self, image: np.ndarray, profile: BookProfile) -> np.ndarray:
        # 测量原图的投影法角度作为基线
        skew_angle = self._detect_skew(image)

        # 优先尝试透视校正（同时完成校正+裁切到边框）
        result = self._perspective_correct(image)
        if result is not None:
            # 透视校正成功即采用：它不仅校正倾斜，还裁切到边框区域
            # 校正后残余角度验证仅在原图有明显倾斜时才需要
            if abs(skew_angle) < self.MIN_CORRECTION_ANGLE:
                return result  # 原图已正，透视校正主要用于裁切
            after_angle = abs(self._detect_skew(result))
            if after_angle <= abs(skew_angle):
                return result
            # 透视校正使倾斜变糟，回退

        # 回退到投影法旋转（不裁切）
        if abs(skew_angle) < self.MIN_CORRECTION_ANGLE:
            return image
        if abs(skew_angle) > self.MAX_CORRECTION_ANGLE:
            return image
        return self._rotate(image, skew_angle)

    # ─── 透视校正 ─────────────────────────────────────────────

    def _perspective_correct(self, image: np.ndarray) -> np.ndarray | None:
        """检测边框四角并透视校正。失败返回 None。"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        h, w = gray.shape

        # LSD 检测线段
        lsd_lines = self._detect_lsd_lines(gray)
        if not lsd_lines:
            return None

        h_lines = [ln for ln in lsd_lines if ln["type"] == "horizontal"]
        v_lines = [ln for ln in lsd_lines if ln["type"] == "vertical"]

        if len(h_lines) < 3 or len(v_lines) < 3:
            return None

        # 共线性聚类
        h_clusters = cluster_lines(h_lines, "h", pos_tol=15, max_gap=60)
        v_clusters = cluster_lines(v_lines, "v", pos_tol=15, max_gap=60)

        # 检测四边框
        top = _find_border_pair(h_clusters, "min", w, h)
        bottom = _find_border_pair(h_clusters, "max", w, h)
        left = _find_border_pair(v_clusters, "min", h, w)
        right = _find_border_pair(v_clusters, "max", h, w)

        # 需要检测到全部 4 条边框
        if (top["outer"] is None or bottom["outer"] is None or
                left["outer"] is None or right["outer"] is None):
            return None

        # 检查覆盖率：边框线至少覆盖对应方向的 40%
        min_h_coverage = w * 0.4
        min_v_coverage = h * 0.4
        if (top["outer"]["total_length"] < min_h_coverage or
                bottom["outer"]["total_length"] < min_h_coverage or
                left["outer"]["total_length"] < min_v_coverage or
                right["outer"]["total_length"] < min_v_coverage):
            return None

        t_slope = top["outer"]["slope"]
        t_int = top["outer"]["intercept"]
        b_slope = bottom["outer"]["slope"]
        b_int = bottom["outer"]["intercept"]
        l_slope = left["outer"]["slope"]
        l_int = left["outer"]["intercept"]
        r_slope = right["outer"]["slope"]
        r_int = right["outer"]["intercept"]

        # 检查各边 slope 是否合理（不超过 MAX_CORRECTION_ANGLE）
        max_slope = np.tan(np.radians(self.MAX_CORRECTION_ANGLE))
        if (abs(t_slope) > max_slope or abs(b_slope) > max_slope or
                abs(l_slope) > max_slope or abs(r_slope) > max_slope):
            return None

        # 计算四角点
        tl = _intersect_hv(t_slope, t_int, l_slope, l_int)
        tr = _intersect_hv(t_slope, t_int, r_slope, r_int)
        bl = _intersect_hv(b_slope, b_int, l_slope, l_int)
        br = _intersect_hv(b_slope, b_int, r_slope, r_int)

        # 验证角点在图像范围内（允许少量越界）
        margin = max(w, h) * 0.05
        for (px, py) in [tl, tr, bl, br]:
            if px < -margin or px > w + margin or py < -margin or py > h + margin:
                return None

        # 验证形成的是合理的四边形（面积 > 原图 20%）
        src_pts = np.array([tl, tr, br, bl], dtype=np.float32)
        area = cv2.contourArea(src_pts)
        if area < w * h * 0.2:
            return None

        # 检查是否实际需要校正（角度太小则跳过）
        max_skew = max(abs(t_slope), abs(b_slope), abs(l_slope), abs(r_slope))
        if max_skew < np.tan(np.radians(self.MIN_CORRECTION_ANGLE)):
            return None

        # 目标矩形尺寸（边框区域映射后的大小）
        frame_w = int(max(self._dist(tl, tr), self._dist(bl, br)))
        frame_h = int(max(self._dist(tl, bl), self._dist(tr, br)))

        # 边框直接映射到 (0,0) 为原点的矩形
        # 输出图像 = 边框区域，黑边/邻页残留/书脊阴影全部裁掉
        dst_pts = np.array([
            [0, 0],
            [frame_w, 0],
            [frame_w, frame_h],
            [0, frame_h],
        ], dtype=np.float32)

        M = cv2.getPerspectiveTransform(src_pts, dst_pts)

        corrected = cv2.warpPerspective(image, M, (frame_w, frame_h),
                                        flags=cv2.INTER_LINEAR,
                                        borderMode=cv2.BORDER_REPLICATE)
        return corrected

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
                continue  # 忽略斜线

            result.append({
                "x1": float(x1), "y1": float(y1),
                "x2": float(x2), "y2": float(y2),
                "length": float(length),
                "width": width,
                "type": line_type,
            })

        return result

    @staticmethod
    def _dist(p1: tuple, p2: tuple) -> float:
        """两点距离。"""
        return np.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    # ─── 投影法旋转（回退方案） ───────────────────────────────

    def _detect_skew(self, image: np.ndarray) -> float:
        """投影法检测倾斜角度。两步搜索：粗搜 + 精搜。"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        h, w = gray.shape

        scale = min(1.0, 800.0 / max(h, w))
        if scale < 1.0:
            small = cv2.resize(gray, None, fx=scale, fy=scale,
                               interpolation=cv2.INTER_AREA)
        else:
            small = gray

        edges = cv2.Canny(small, 50, 150, apertureSize=3)
        sh, sw = edges.shape

        # 粗搜
        best_angle = 0.0
        best_score = -1.0
        coarse_angles = np.arange(-self._SEARCH_RANGE,
                                  self._SEARCH_RANGE + self._COARSE_STEP,
                                  self._COARSE_STEP)
        for a in coarse_angles:
            score = self._projection_score(edges, a, sh, sw)
            if score > best_score:
                best_score = score
                best_angle = a

        # 精搜
        fine_angles = np.arange(best_angle - self._FINE_RANGE,
                                best_angle + self._FINE_RANGE + self._FINE_STEP,
                                self._FINE_STEP)
        for a in fine_angles:
            score = self._projection_score(edges, a, sh, sw)
            if score > best_score:
                best_score = score
                best_angle = a

        return round(float(best_angle), 2)

    @staticmethod
    def _projection_score(edges: np.ndarray, angle: float,
                          h: int, w: int) -> float:
        """水平投影尖锐度（sum of squares）。"""
        if abs(angle) < 1e-6:
            proj = np.sum(edges, axis=1, dtype=np.float64)
        else:
            M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
            rotated = cv2.warpAffine(edges, M, (w, h),
                                     flags=cv2.INTER_NEAREST)
            proj = np.sum(rotated, axis=1, dtype=np.float64)
        return float(np.sum(proj ** 2))

    def _rotate(self, image: np.ndarray, angle: float) -> np.ndarray:
        """旋转图像校正倾斜。"""
        h, w = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(image, M, (w, h),
                                 flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_REPLICATE)
        return rotated
