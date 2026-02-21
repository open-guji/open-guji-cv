"""透视/形变矫正预处理器。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np

from .base import BasePreprocessor

if TYPE_CHECKING:
    from ..profile import BookProfile


class NormalizePreprocessor(BasePreprocessor):
    """轻度透视矫正和倾斜校正。

    通过检测边框直线的倾斜角度来校正整体倾斜。
    """

    name = "normalize"
    priority = 60

    # 最大校正角度（度），超过此角度不校正（避免误操作）
    MAX_CORRECTION_ANGLE = 5.0
    # 最小校正角度（度），低于此角度不值得校正
    MIN_CORRECTION_ANGLE = 0.3

    @classmethod
    def is_needed(cls, profile: BookProfile) -> bool:
        return True  # 始终执行

    def process(self, image: np.ndarray, profile: BookProfile) -> np.ndarray:
        angle = self._detect_skew(image)

        if abs(angle) < self.MIN_CORRECTION_ANGLE:
            return image
        if abs(angle) > self.MAX_CORRECTION_ANGLE:
            return image

        return self._rotate(image, angle)

    def _detect_skew(self, image: np.ndarray) -> float:
        """检测图像倾斜角度。

        使用霍夫变换检测接近水平/垂直的直线，
        计算这些直线偏离水平/垂直的平均角度。

        Returns:
            倾斜角度（度），正值为逆时针。
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

        # 边缘检测
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)

        # 霍夫变换检测直线
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180,
                                threshold=100, minLineLength=100,
                                maxLineGap=10)

        if lines is None:
            return 0.0

        # 收集接近水平的直线的角度
        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            dx = x2 - x1
            dy = y2 - y1
            angle = np.degrees(np.arctan2(dy, dx))
            # 只收集接近水平的线（偏离 0° 不超过 15°）
            if abs(angle) < 15:
                angles.append(angle)

        if not angles:
            return 0.0

        # 用中位数更稳健
        return float(np.median(angles))

    def _rotate(self, image: np.ndarray, angle: float) -> np.ndarray:
        """旋转图像校正倾斜。"""
        h, w = image.shape[:2]
        center = (w // 2, h // 2)

        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(image, M, (w, h),
                                 flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_REPLICATE)
        return rotated
