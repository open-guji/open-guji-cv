"""书脊阴影裁剪预处理器：检测并裁剪页面侧边的书脊阴影。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np

from .base import BasePreprocessor

if TYPE_CHECKING:
    from ..profile import BookProfile


class CropSpinePreprocessor(BasePreprocessor):
    """检测并裁剪书脊阴影。

    书脊阴影通常出现在页面的左侧或右侧边缘，
    表现为一条从上到下贯穿的暗色纵向条纹。
    """

    name = "crop_spine"
    priority = 25

    # 搜索书脊的边缘区域宽度比例
    EDGE_SEARCH_RATIO = 0.15
    # 暗度阈值：比周围暗多少才算书脊
    DARKNESS_THRESHOLD = 20

    @classmethod
    def is_needed(cls, profile: BookProfile) -> bool:
        return profile.has_spine_shadow

    def process(self, image: np.ndarray, profile: BookProfile) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        h, w = gray.shape[:2]

        edge_width = int(w * self.EDGE_SEARCH_RATIO)

        # 检测左侧和右侧哪边有书脊阴影
        left_score, left_boundary = self._detect_spine_edge(gray, "left", edge_width)
        right_score, right_boundary = self._detect_spine_edge(gray, "right", edge_width)

        # 裁剪得分更高的那一侧
        if left_score > right_score and left_score > 0.3:
            return image[:, left_boundary:].copy()
        elif right_score > 0.3:
            return image[:, :right_boundary].copy()

        return image

    def _detect_spine_edge(self, gray: np.ndarray, side: str,
                           edge_width: int) -> tuple[float, int]:
        """检测一侧的书脊阴影边界。

        Returns:
            (置信度, 边界x坐标)
        """
        h, w = gray.shape

        if side == "left":
            strip = gray[:, :edge_width]
        else:
            strip = gray[:, w - edge_width:]

        # 每列的平均亮度
        col_means = np.mean(strip, axis=0)

        if len(col_means) < 5:
            return 0.0, 0

        # 找到亮度最低的区域（书脊阴影）
        min_idx = np.argmin(col_means)
        min_val = col_means[min_idx]

        # 与边缘均值的比较
        edge_mean = np.mean(col_means[-5:] if side == "left" else col_means[:5])
        darkness_diff = edge_mean - min_val

        if darkness_diff < self.DARKNESS_THRESHOLD:
            return 0.0, 0

        # 找到阴影结束的位置（亮度恢复到正常水平的位置）
        threshold = min_val + darkness_diff * 0.6

        if side == "left":
            boundary = min_idx
            for i in range(min_idx, len(col_means)):
                if col_means[i] > threshold:
                    boundary = i
                    break
        else:
            boundary = w - edge_width + min_idx
            for i in range(min_idx, -1, -1):
                if col_means[i] > threshold:
                    boundary = w - edge_width + i
                    break

        score = min(1.0, darkness_diff / 40.0)
        return score, boundary
