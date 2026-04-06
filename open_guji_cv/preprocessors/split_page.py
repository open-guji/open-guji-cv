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
    返回命名子图列表：[("right", 右半页), ("left", 左半页)]。
    古籍从右往左读，右半页在前。
    """

    name = "split_page"
    priority = 10

    @classmethod
    def is_needed(cls, profile: BookProfile) -> bool:
        return profile.needs_split

    def process(self, image: np.ndarray, profile: BookProfile
                ) -> list[tuple[str, np.ndarray]]:
        center_x = self._find_center_line(image)

        right_half = image[:, center_x:].copy()
        left_half = image[:, :center_x].copy()

        return [("right", right_half), ("left", left_half)]

    def _find_center_line(self, image: np.ndarray) -> int:
        """检测中线（版心）位置。

        武英殿本等刻本的中缝结构：左边框线（暗）—— 版心空白（亮）—— 右边框线（暗）。
        拆分点应在两条边框线之间的亮带中央。

        算法：
        1. 在图片中央区域用垂直投影找暗带（边框线）
        2. 找到最显著的一对暗带（间距合理的相邻暗带）
        3. 取两暗带中点作为拆分位置
        4. 回退：若未找到暗带对，使用最暗位置
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        h, w = gray.shape

        # 使用中间 60% 高度区域，避免天头地脚干扰
        y_start = int(h * 0.2)
        y_end = int(h * 0.8)
        projection = np.mean(gray[y_start:y_end, :], axis=0)

        # 平滑
        kernel_size = max(w // 200, 3)
        if kernel_size % 2 == 0:
            kernel_size += 1
        smoothed = np.convolve(projection,
                               np.ones(kernel_size) / kernel_size,
                               mode="same")

        # 在中央 30% 区域搜索
        search_start = int(w * 0.35)
        search_end = int(w * 0.65)

        # 自适应暗带阈值：区域中位数 - 一定偏移
        region = smoothed[search_start:search_end]
        median_val = np.median(region)
        dark_threshold = median_val - 30

        # 找暗带（连续暗像素段）
        dark_bands: list[tuple[int, int]] = []
        in_dark = False
        band_start = 0
        for x in range(search_start, search_end):
            if smoothed[x] < dark_threshold and not in_dark:
                in_dark = True
                band_start = x
            elif smoothed[x] >= dark_threshold and in_dark:
                in_dark = False
                dark_bands.append((band_start, x))
        if in_dark:
            dark_bands.append((band_start, search_end))

        # 过滤过窄的暗带（噪声）
        min_band_width = max(w // 500, 2)
        dark_bands = [(s, e) for s, e in dark_bands if e - s >= min_band_width]

        # 找最佳暗带对：间距在合理范围内（图宽的 2%~15%）
        min_gap = int(w * 0.02)
        max_gap = int(w * 0.15)
        best_pair = None
        best_score = float("inf")

        for i in range(len(dark_bands)):
            for j in range(i + 1, len(dark_bands)):
                gap = dark_bands[j][0] - dark_bands[i][1]
                if min_gap <= gap <= max_gap:
                    # 评分：两条暗带越暗越好
                    left_dark = np.min(smoothed[dark_bands[i][0]:dark_bands[i][1]])
                    right_dark = np.min(smoothed[dark_bands[j][0]:dark_bands[j][1]])
                    score = left_dark + right_dark
                    if score < best_score:
                        best_score = score
                        best_pair = (dark_bands[i], dark_bands[j])

        if best_pair is not None:
            left_band, right_band = best_pair
            # 拆分点：左暗带右端与右暗带左端的中点
            center_x = (left_band[1] + right_band[0]) // 2
            return center_x

        # 回退：找最暗位置
        center_offset = np.argmin(region)
        return search_start + center_offset
