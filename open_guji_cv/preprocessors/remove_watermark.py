"""水印去除预处理器。

算法：p90 模板精确线条检测 + 逐页 inpaint
1. setup：p90 堆叠 → 文字消失、水印线条保留
2. 连通域分析定位水印区域（凸包 + 膨胀）→ 限定范围
3. 在水印区域内，用 top-hat 从 p90 模板检测线条像素（不膨胀）
4. 逐页：只 inpaint 这些线条像素

关键：不膨胀线条掩码，避免覆盖文字。p90 模板中线条因页间偏移
略微变粗（~2-3px），但不膨胀就不会严重影响文字。
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

# ── 水印区域检测（粗定位） ──
_BG_BLUR_KSIZE = 201
_BG_BLUR_SIGMA = 70
_COARSE_THRESH = 25
_CONNECT_KSIZE = 11
_CONNECT_DILATE_ITERS = 3
_CONNECT_CLOSE_ITERS = 3
_MIN_AREA_RATIO = 0.005
_MAX_DIM_RATIO = 0.5
_HULL_EXPAND_RADIUS = 70

# ── 线条检测 ──
_TOPHAT_KSIZE = 15
_LINE_THRESH = 8

# ── inpaint ──
_INPAINT_RADIUS = 2  # 小半径，从最近邻取色


class RemoveWatermarkPreprocessor(BasePreprocessor):
    """通过多页堆叠检测水印线条，逐像素 inpaint 去除。"""

    name = "remove_watermark"
    priority = 5

    def __init__(self):
        self._line_mask: np.ndarray | None = None
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

        # 步骤1：定位水印区域
        region_mask, n_kept = self._detect_watermark_region(p90_gray, h, w)
        if n_kept == 0:
            print("    水印去除：未检测到水印区域，跳过")
            return

        # 步骤2：在水印区域内，从 p90 模板精确检测线条（不膨胀）
        line_mask = self._detect_line_pixels(p90_gray, region_mask)

        if cv2.countNonZero(line_mask) == 0:
            print("    水印去除：未检测到水印线条，跳过")
            return

        self._line_mask = line_mask
        self._ready = True

        n_pixels = cv2.countNonZero(line_mask)
        print(f"    水印线条掩码: {n_kept} 个区域, "
              f"{n_pixels} 像素 ({n_pixels*100/(h*w):.1f}%)")

    @staticmethod
    def _detect_watermark_region(p90_gray, h, w):
        """用连通域分析定位水印区域，取凸包并膨胀。"""
        bg_gray = cv2.GaussianBlur(p90_gray, (_BG_BLUR_KSIZE, _BG_BLUR_KSIZE),
                                   _BG_BLUR_SIGMA)
        diff_abs = cv2.absdiff(p90_gray, bg_gray)
        _, binary = cv2.threshold(diff_abs, _COARSE_THRESH, 255, cv2.THRESH_BINARY)

        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                      (_CONNECT_KSIZE, _CONNECT_KSIZE))
        connected = cv2.dilate(binary, k, iterations=_CONNECT_DILATE_ITERS)
        connected = cv2.morphologyEx(connected, cv2.MORPH_CLOSE, k,
                                     iterations=_CONNECT_CLOSE_ITERS)

        n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(connected)
        min_area = h * w * _MIN_AREA_RATIO

        hull_mask = np.zeros((h, w), dtype=np.uint8)
        n_kept = 0
        for i in range(1, n_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            bw_c = stats[i, cv2.CC_STAT_WIDTH]
            bh_c = stats[i, cv2.CC_STAT_HEIGHT]
            if area < min_area:
                continue
            if bw_c > w * _MAX_DIM_RATIO and bh_c > h * _MAX_DIM_RATIO:
                continue
            component = ((labels == i) * 255).astype(np.uint8)
            contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL,
                                           cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                hull = cv2.convexHull(np.vstack(contours))
                cv2.fillConvexPoly(hull_mask, hull, 255)
            n_kept += 1

        r = _HULL_EXPAND_RADIUS
        k_big = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r * 2 + 1, r * 2 + 1))
        hull_mask = cv2.dilate(hull_mask, k_big, iterations=1)

        return hull_mask, n_kept

    @staticmethod
    def _detect_line_pixels(p90_gray, region_mask):
        """在水印区域内，从 p90 模板检测线条像素。不膨胀。"""
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                      (_TOPHAT_KSIZE, _TOPHAT_KSIZE))

        black_tophat = cv2.morphologyEx(p90_gray, cv2.MORPH_BLACKHAT, k)
        white_tophat = cv2.morphologyEx(p90_gray, cv2.MORPH_TOPHAT, k)

        _, black_mask = cv2.threshold(black_tophat, _LINE_THRESH, 255,
                                      cv2.THRESH_BINARY)
        _, white_mask = cv2.threshold(white_tophat, _LINE_THRESH, 255,
                                      cv2.THRESH_BINARY)

        line_mask = cv2.bitwise_or(black_mask, white_mask)
        # 只保留水印区域内
        line_mask = cv2.bitwise_and(line_mask, region_mask)

        return line_mask

    def process(self, image: np.ndarray, profile: BookProfile) -> np.ndarray:
        """对单张图片去除水印：只 inpaint 线条像素。"""
        if not self._ready:
            return image

        h, w = image.shape[:2]
        mask = self._line_mask

        if mask.shape[:2] != (h, w):
            mask = cv2.resize(mask, (w, h),
                              interpolation=cv2.INTER_NEAREST)

        return cv2.inpaint(image, mask, _INPAINT_RADIUS, cv2.INPAINT_TELEA)
