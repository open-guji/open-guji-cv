"""颜色模式分析器：检测黑白/彩色、底色、文字色、边框色。"""

import cv2
import numpy as np

from .base import BaseAnalyzer


class ColorModeAnalyzer(BaseAnalyzer):
    """检测古籍图像的颜色模式。

    通过分析 HSV 饱和度分布来判断：
    - 黑白图像：饱和度整体很低 → background_color="white"
    - 彩色图像：存在高饱和度区域 → background_color="xuan"/"other"
    同时检测文字和边框的颜色（黑/红/其他）。
    """

    name = "color_mode"

    SATURATION_THRESHOLD = 30
    COLOR_RATIO_THRESHOLD = 0.08

    def analyze(self, images: list[np.ndarray]) -> dict:
        color_ratios = []
        hue_histograms = []

        for img in images:
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            saturation = hsv[:, :, 1]

            high_sat_mask = saturation > self.SATURATION_THRESHOLD
            ratio = np.count_nonzero(high_sat_mask) / saturation.size
            color_ratios.append(ratio)

            if ratio > self.COLOR_RATIO_THRESHOLD:
                hue_values = hsv[:, :, 0][high_sat_mask]
                hist, _ = np.histogram(hue_values, bins=36, range=(0, 180))
                hue_histograms.append(hist)

        avg_ratio = np.mean(color_ratios)
        is_colored = avg_ratio > self.COLOR_RATIO_THRESHOLD

        result = {
            "color_mode": "colored" if is_colored else "bw",
            "_confidence": {"color_mode": min(1.0, abs(avg_ratio - self.COLOR_RATIO_THRESHOLD) * 10 + 0.5)},
        }

        if is_colored and hue_histograms:
            result["background_color"] = self._classify_background(hue_histograms)
            result["border_color"] = self._detect_border_color(images)
        else:
            result["background_color"] = "white"
            result["border_color"] = "black"

        result["text_color"] = self._detect_text_color(images)

        return result

    def _classify_background(self, hue_histograms: list[np.ndarray]) -> str:
        """分类底色：xuan (宣纸色) 或 other。"""
        combined = np.sum(hue_histograms, axis=0)
        dominant_bin = np.argmax(combined)
        dominant_hue = dominant_bin * 5  # 每个 bin 5 度

        # 宣纸色范围：暖色调 (hue 5-40, 即橙黄色系)
        if 5 <= dominant_hue <= 40:
            return "xuan"
        return "other"

    def _detect_text_color(self, images: list[np.ndarray]) -> str:
        """检测文字颜色：black / red / other。

        在内容区域提取墨迹像素，检查是否有大量红色。
        """
        red_ratios = []

        for img in images:
            h, w = img.shape[:2]
            # 内容区域（避开边框）
            roi = img[int(h * 0.15):int(h * 0.85), int(w * 0.15):int(w * 0.85)]

            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

            # 提取暗像素（文字墨迹）—— Otsu 二值化
            _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            ink_mask = bw > 0

            if np.count_nonzero(ink_mask) < 100:
                continue

            # 在墨迹像素中检测红色 (H < 10 or H > 170, S > 50)
            hue = hsv[:, :, 0]
            sat = hsv[:, :, 1]
            red_mask = ink_mask & (sat > 50) & ((hue < 10) | (hue > 170))

            red_ratio = np.count_nonzero(red_mask) / np.count_nonzero(ink_mask)
            red_ratios.append(red_ratio)

        if red_ratios:
            avg_red = np.mean(red_ratios)
            if avg_red > 0.3:
                return "red"

        return "black"

    def _detect_border_color(self, images: list[np.ndarray]) -> str:
        """检测边框颜色：black / red / other。

        采样边框区域的暗像素，检测色调。
        """
        red_counts = 0
        total = 0

        for img in images:
            h, w = img.shape[:2]
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            search = int(min(h, w) * 0.12)

            # 四条边的条带
            strips_bgr = [
                img[:, :search],          # 左
                img[:, w - search:],       # 右
                img[:search, :],           # 上
                img[h - search:, :],       # 下
            ]
            strips_hsv = [
                hsv[:, :search],
                hsv[:, w - search:],
                hsv[:search, :],
                hsv[h - search:, :],
            ]
            strips_gray = [
                gray[:, :search],
                gray[:, w - search:],
                gray[:search, :],
                gray[h - search:, :],
            ]

            for sg, sh in zip(strips_gray, strips_hsv):
                # 找暗像素（边框线）
                dark_mask = sg < (np.median(sg) - 30)
                if np.count_nonzero(dark_mask) < 20:
                    continue

                total += 1
                hue_vals = sh[:, :, 0][dark_mask]
                sat_vals = sh[:, :, 1][dark_mask]

                # 红色边框：H < 10 or H > 170, S > 40
                red_mask = (sat_vals > 40) & ((hue_vals < 10) | (hue_vals > 170))
                if np.count_nonzero(red_mask) / len(hue_vals) > 0.3:
                    red_counts += 1

        if total > 0 and red_counts / total > 0.3:
            return "red"
        return "black"
