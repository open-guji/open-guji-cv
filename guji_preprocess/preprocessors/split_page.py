"""筒子页拆分预处理器：将未剪切的整页拆分为左右两半页。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np

from .base import BasePreprocessor

if TYPE_CHECKING:
    from ..profile import BookProfile


class SplitPagePreprocessor(BasePreprocessor):
    """将未剪切的筒子页拆分为左右两半页。

    检测中线位置（版心/书口），然后沿中线切分。
    中线检测方法：
    1. 对灰度图做垂直投影（每列像素均值）
    2. 在图像中央区域寻找暗值峰（版心界栏通常最暗）
    """

    name = "split_page"
    priority = 10  # 最先执行

    @classmethod
    def is_needed(cls, profile: BookProfile) -> bool:
        return profile.is_uncut

    def process(self, image: np.ndarray, profile: BookProfile
                ) -> list[np.ndarray]:
        h, w = image.shape[:2]
        center_x = self._find_center_line(image)

        # 切分为左右两半
        left_half = image[:, :center_x].copy()
        right_half = image[:, center_x:].copy()

        # 返回右半页（奇数页）在前，左半页（偶数页）在后
        # 古籍从右往左读，右半页是正面
        return [right_half, left_half]

    def _find_center_line(self, image: np.ndarray) -> int:
        """检测中线（版心）位置。"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        h, w = gray.shape

        # 垂直投影：每列的平均亮度
        projection = np.mean(gray, axis=0)

        # 在中央 30% 区域搜索最暗的纵向带（版心界栏）
        search_start = int(w * 0.35)
        search_end = int(w * 0.65)
        search_region = projection[search_start:search_end]

        # 用滑动窗口平滑，找最暗位置
        kernel_size = max(w // 100, 3)
        if kernel_size % 2 == 0:
            kernel_size += 1
        smoothed = np.convolve(search_region,
                               np.ones(kernel_size) / kernel_size,
                               mode="same")

        center_offset = np.argmin(smoothed)
        center_x = search_start + center_offset

        return center_x
