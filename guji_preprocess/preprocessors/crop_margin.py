"""页边距裁剪预处理器：裁剪图像外部的白色/灰色空白区域。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np

from .base import BasePreprocessor

if TYPE_CHECKING:
    from ..profile import BookProfile


class CropMarginPreprocessor(BasePreprocessor):
    """裁剪图像外部的白色页边距，保留古籍内容区域。

    适用于：图像边缘有明显的白色/浅色空白背景，
    内部是灰色/彩色的古籍扫描内容。
    """

    name = "crop_margin"
    priority = 20

    # 前景/背景亮度差异阈值
    BRIGHTNESS_DIFF_THRESHOLD = 20
    # 最小裁剪边距（像素），避免裁太紧
    MIN_PADDING = 5

    @classmethod
    def is_needed(cls, profile: BookProfile) -> bool:
        return profile.has_white_margin

    def process(self, image: np.ndarray, profile: BookProfile) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        h, w = gray.shape[:2]

        # 用 Otsu 自动阈值区分前景和背景
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # 形态学操作，连接前景区域
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 20))
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        # 找到前景区域的 bounding box
        coords = cv2.findNonZero(closed)
        if coords is None:
            return image

        x, y, bw, bh = cv2.boundingRect(coords)

        # 添加少量 padding
        x1 = max(0, x - self.MIN_PADDING)
        y1 = max(0, y - self.MIN_PADDING)
        x2 = min(w, x + bw + self.MIN_PADDING)
        y2 = min(h, y + bh + self.MIN_PADDING)

        return image[y1:y2, x1:x2].copy()
