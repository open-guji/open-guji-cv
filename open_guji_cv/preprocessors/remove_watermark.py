"""水印去除预处理器。

算法：精确线条检测 + inpaint
1. setup：p90 堆叠 → 文字消失、水印线条保留
2. 用 morphological top-hat 精确检测黑线和白线的逐像素位置
   - 黑线：closing(p90) - p90  （black top-hat，暗特征）
   - 白线：p90 - opening(p90)  （white top-hat，亮特征）
3. 膨胀 1px 确保覆盖线条边缘
4. 逐页：只 inpaint 线条像素 → 用周围颜色填充，不模糊其他区域
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

from .base import BasePreprocessor
from ..utils.image_io import imread

if TYPE_CHECKING:
    from ..profile import BookProfile

# ── 线条检测参数 ──
_TOPHAT_KSIZE = 15       # top-hat 形态学核大小
_LINE_THRESH = 8         # 线条检测阈值
_LINE_DILATE_ITERS = 1   # 线条掩码膨胀次数

# ── inpaint 参数 ──
_INPAINT_RADIUS = 3      # inpaint 半径（小半径=从近邻取色）


class RemoveWatermarkPreprocessor(BasePreprocessor):
    """通过多页堆叠精确检测水印线条，逐像素 inpaint 去除。"""

    name = "remove_watermark"
    priority = 5

    def __init__(self):
        self._line_mask: np.ndarray | None = None  # 线条像素掩码 (uint8)
        self._ready = False

    @classmethod
    def is_needed(cls, profile: BookProfile) -> bool:
        return "watermark" in profile.interferences

    def setup(self, image_paths: list[Path], profile: BookProfile) -> None:
        """预扫描所有页面，构建水印线条掩码。"""
        if self._ready:
            return

        images = []
        for p in image_paths:
            img = imread(str(p))
            if img is not None:
                images.append(img)

        if len(images) < 3:
            print("    水印去除：页面不足（<3），跳过")
            return

        # 统一尺寸
        target_shape = images[0].shape[:2]
        stack = []
        for img in images:
            if img.shape[:2] != target_shape:
                img = cv2.resize(img, (target_shape[1], target_shape[0]))
            stack.append(img.astype(np.float32))
        stack = np.array(stack)

        h, w = target_shape
        p90 = np.percentile(stack, 90, axis=0).astype(np.uint8)
        p90_gray = cv2.cvtColor(p90, cv2.COLOR_BGR2GRAY)

        # ── 精确检测线条像素 ──
        line_mask = self._detect_line_pixels(p90_gray)

        if cv2.countNonZero(line_mask) == 0:
            print("    水印去除：未检测到水印线条，跳过")
            return

        self._line_mask = line_mask
        self._ready = True

        n_pixels = cv2.countNonZero(line_mask)
        print(f"    水印线条掩码: {n_pixels} 像素 "
              f"({n_pixels*100/(h*w):.1f}%)")

    @staticmethod
    def _detect_line_pixels(p90_gray):
        """用 morphological top-hat 精确检测黑线和白线。

        p90 中文字已消失，水印线条清晰，可精确提取线条像素。
        - Black top-hat (closing - original)：检测暗于周围的细线（黑线）
        - White top-hat (original - opening)：检测亮于周围的细线（白线）
        """
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                      (_TOPHAT_KSIZE, _TOPHAT_KSIZE))

        # 黑线：closing 填充暗特征后与原图的差
        black_tophat = cv2.morphologyEx(p90_gray, cv2.MORPH_BLACKHAT, k)
        # 白线：原图与 opening 去除亮特征后的差
        white_tophat = cv2.morphologyEx(p90_gray, cv2.MORPH_TOPHAT, k)

        # 阈值化
        _, black_mask = cv2.threshold(black_tophat, _LINE_THRESH, 255,
                                      cv2.THRESH_BINARY)
        _, white_mask = cv2.threshold(white_tophat, _LINE_THRESH, 255,
                                      cv2.THRESH_BINARY)

        # 合并黑线和白线
        line_mask = cv2.bitwise_or(black_mask, white_mask)

        # 膨胀 1px 确保覆盖线条边缘
        if _LINE_DILATE_ITERS > 0:
            k_dilate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            line_mask = cv2.dilate(line_mask, k_dilate,
                                   iterations=_LINE_DILATE_ITERS)

        return line_mask

    def process(self, image: np.ndarray, profile: BookProfile) -> np.ndarray:
        """对单张图片去除水印：inpaint 线条像素，用周围颜色填充。"""
        if not self._ready:
            return image

        h, w = image.shape[:2]
        mask = self._line_mask

        # 尺寸不匹配时 resize 掩码
        if mask.shape[:2] != (h, w):
            mask = cv2.resize(mask, (w, h),
                              interpolation=cv2.INTER_NEAREST)

        return cv2.inpaint(image, mask, _INPAINT_RADIUS, cv2.INPAINT_TELEA)
