"""自适应二值化预处理器：根据颜色模式选择最佳二值化策略，并去除小噪点。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np

from .base import BasePreprocessor

if TYPE_CHECKING:
    from ..profile import BookProfile


class BinarizePreprocessor(BasePreprocessor):
    """自适应二值化 + 噪点去除。

    根据 BookProfile 的 color_mode 选择策略：
    - 黑白图像：直接使用 Otsu 全局阈值或自适应阈值
    - 彩色图像：先提取文字通道（基于底色信息），再二值化

    最后通过连通域分析去除面积过小的噪点。
    """

    name = "binarize"
    priority = 50

    # 噪点去除参数
    NOISE_MAX_AREA = 10  # 面积 <= 此值的黑色连通域视为噪点并移除

    @classmethod
    def is_needed(cls, profile: BookProfile) -> bool:
        return True  # 始终执行

    def process(self, image: np.ndarray, profile: BookProfile) -> np.ndarray:
        if profile.is_colored:
            binary = self._binarize_colored(image, profile)
        else:
            binary = self._binarize_bw(image)

        # TODO: 去噪容易误删有用内容，暂时禁用
        # binary = self._remove_small_noise(binary)

        return binary

    def _binarize_bw(self, image: np.ndarray) -> np.ndarray:
        """黑白图像二值化。"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

        # 自适应阈值：对光照不均的古籍扫描更稳健
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, blockSize=31, C=10
        )

        return binary

    def _binarize_colored(self, image: np.ndarray, profile: BookProfile) -> np.ndarray:
        """彩色图像二值化：提取文字通道后再二值化。"""
        if len(image.shape) == 2:
            return self._binarize_bw(image)

        # 转为 HSV
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

        # 根据底色决定策略
        if profile.background_color == "red":
            # 红底黑字：用饱和度通道来区分底色和文字
            # 文字（黑色）饱和度低，底色（红色）饱和度高
            sat = hsv[:, :, 1]
            val = hsv[:, :, 2]
            # 文字：低饱和度 + 低亮度
            text_mask = ((sat < 80) & (val < 150)).astype(np.uint8) * 255
        elif profile.background_color == "yellow":
            # 黄底黑字：类似策略
            sat = hsv[:, :, 1]
            val = hsv[:, :, 2]
            text_mask = ((sat < 60) & (val < 160)).astype(np.uint8) * 255
        else:
            # 通用策略：灰度后自适应阈值
            return self._binarize_bw(image)

        # 形态学清理
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        text_mask = cv2.morphologyEx(text_mask, cv2.MORPH_CLOSE, kernel)

        # 反转：让文字为白色（255），背景为黑色（0），
        # 但古籍处理通常习惯文字为黑、背景为白
        result = 255 - text_mask

        return result

    def _remove_small_noise(self, binary: np.ndarray) -> np.ndarray:
        """通过连通域分析去除面积过小的噪点。

        binary: 255=背景(白), 0=前景(黑)
        面积 <= NOISE_MAX_AREA 的黑色连通域被置为白色(255)。
        """
        # 反转：connectedComponents 检测白色(255)连通域，
        # 所以先反转让前景(黑色噪点/文字)变成255
        inv = cv2.bitwise_not(binary)

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
            inv, connectivity=8)

        # label 0 是背景（原图白色区域），从 label 1 开始检查
        for label_id in range(1, num_labels):
            area = stats[label_id, cv2.CC_STAT_AREA]
            if area <= self.NOISE_MAX_AREA:
                # 将该小连通域在原图中置为白色（背景）
                binary[labels == label_id] = 255

        return binary
