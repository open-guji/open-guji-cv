"""页边距裁剪预处理器：裁剪到边框外缘，去除所有边框外的多余区域。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np

from .base import BasePreprocessor
from ..utils.content_bounds import find_content_bounds

if TYPE_CHECKING:
    from ..profile import BookProfile


class CropMarginPreprocessor(BasePreprocessor):
    """裁剪图像到边框外缘，去除白色/黑色页边距和扫描背景。

    适用于所有古籍图像，自动处理：
    - 白色扫描背景（如 book1/2/5）
    - 黑色填充背景（如 book4）
    - 无明显页边距（如 book3）——几乎不裁切

    算法委托给 utils.content_bounds.find_content_bounds()。
    """

    name = "crop_margin"
    priority = 5

    MIN_CONTENT_RATIO = 0.3
    MIN_DIMENSION = 100

    @classmethod
    def is_needed(cls, profile: BookProfile) -> bool:
        return True

    def process(self, image: np.ndarray, profile: BookProfile) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        h, w = gray.shape[:2]

        if h < self.MIN_DIMENSION or w < self.MIN_DIMENSION:
            return image

        top, bottom, left, right = find_content_bounds(gray)

        content_h = bottom - top + 1
        content_w = right - left + 1
        if content_h < h * self.MIN_CONTENT_RATIO or content_w < w * self.MIN_CONTENT_RATIO:
            return image

        return image[top:bottom + 1, left:right + 1].copy()
