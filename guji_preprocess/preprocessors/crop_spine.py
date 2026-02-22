"""书脊阴影裁剪预处理器：检测并裁剪页面侧边的书脊阴影。

注意：此步骤可能在裁边框（crop_margin）之前执行，因此图片可能还有
白色/黑色页边距。内部先用 find_content_bounds() 定位内容区域，
然后仅在内容区域内检测书脊阴影，避免页边距干扰。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np

from .base import BasePreprocessor
from ..utils.content_bounds import find_content_bounds

if TYPE_CHECKING:
    from ..profile import BookProfile


class CropSpinePreprocessor(BasePreprocessor):
    """检测并裁剪书脊阴影。

    书脊阴影通常出现在页面的左侧或右侧边缘，
    表现为一条从上到下贯穿的暗色纵向条纹。
    """

    name = "crop_spine"
    priority = 25

    # 搜索书脊的边缘区域宽度比例（相对于内容区宽度）
    EDGE_SEARCH_RATIO = 0.15
    # 暗度阈值：比周围暗多少才算书脊
    DARKNESS_THRESHOLD = 20

    @classmethod
    def is_needed(cls, profile: BookProfile) -> bool:
        return profile.has_spine_shadow

    def process(self, image: np.ndarray, profile: BookProfile) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        h, w = gray.shape[:2]

        # 1. 先定位内容区域（排除白色/黑色页边距的干扰）
        c_top, c_bot, c_left, c_right = find_content_bounds(gray)
        content = gray[c_top:c_bot + 1, c_left:c_right + 1]
        ch, cw = content.shape

        edge_width = max(int(cw * self.EDGE_SEARCH_RATIO), 30)

        # 2. 在内容区域内检测左右两侧的书脊阴影
        left_score, left_crop = self._detect_spine_edge(content, "left", edge_width)
        right_score, right_crop = self._detect_spine_edge(content, "right", edge_width)

        # 3. 裁剪得分更高的一侧（在原图坐标系中操作）
        if left_score > right_score and left_score > 0.3:
            # 书脊在内容区左侧，裁掉左侧 left_crop 列
            return image[:, c_left + left_crop:].copy()
        elif right_score > 0.3:
            # 书脊在内容区右侧，裁掉右侧 right_crop 列
            return image[:, :c_right + 1 - right_crop].copy()

        return image

    def _detect_spine_edge(self, content: np.ndarray, side: str,
                           edge_width: int) -> tuple[float, int]:
        """在内容区域的一侧检测书脊阴影。

        Args:
            content: 内容区域灰度图
            side: "left" 或 "right"
            edge_width: 搜索区域宽度

        Returns:
            (置信度 0~1, 需要裁掉的列数)
        """
        ch, cw = content.shape

        if side == "left":
            strip = content[:, :edge_width]
        else:
            strip = content[:, cw - edge_width:]

        col_means = np.mean(strip, axis=0)

        if len(col_means) < 5:
            return 0.0, 0

        # 找到亮度最低的区域（书脊阴影中心）
        min_idx = np.argmin(col_means)
        min_val = col_means[min_idx]

        # 与条带远端（远离边缘的一侧）的均值比较
        if side == "left":
            ref_mean = np.mean(col_means[-5:])
        else:
            ref_mean = np.mean(col_means[:5])

        darkness_diff = ref_mean - min_val

        if darkness_diff < self.DARKNESS_THRESHOLD:
            return 0.0, 0

        # 找到阴影结束的位置（亮度恢复到 60% 水平）
        threshold = min_val + darkness_diff * 0.6

        if side == "left":
            boundary = min_idx
            for i in range(min_idx, len(col_means)):
                if col_means[i] > threshold:
                    boundary = i
                    break
            crop_cols = boundary
        else:
            boundary = min_idx
            for i in range(min_idx, -1, -1):
                if col_means[i] > threshold:
                    boundary = i
                    break
            crop_cols = edge_width - boundary

        score = min(1.0, darkness_diff / 40.0)
        return score, crop_cols
