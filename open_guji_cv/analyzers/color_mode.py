"""颜色模式分析器：检测黑白/彩色、底色、边框色。"""

import cv2
import numpy as np

from .base import BaseAnalyzer


class ColorModeAnalyzer(BaseAnalyzer):
    """检测古籍图像的颜色模式。

    通过分析 HSV 饱和度分布来判断：
    - 黑白图像：饱和度整体很低
    - 彩色图像：存在高饱和度区域，进一步识别底色和边框色
    """

    name = "color_mode"

    # 饱和度阈值：低于此值视为无色彩
    SATURATION_THRESHOLD = 30
    # 高饱和度像素占比阈值：超过此比例视为彩色
    COLOR_RATIO_THRESHOLD = 0.08

    def analyze(self, images: list[np.ndarray]) -> dict:
        color_ratios = []
        hue_histograms = []

        for img in images:
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            saturation = hsv[:, :, 1]

            # 计算高饱和度像素占比
            high_sat_mask = saturation > self.SATURATION_THRESHOLD
            ratio = np.count_nonzero(high_sat_mask) / saturation.size
            color_ratios.append(ratio)

            if ratio > self.COLOR_RATIO_THRESHOLD:
                # 收集高饱和度区域的色调直方图
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
            bg_color, border_color = self._identify_colors(hue_histograms)
            result["background_color"] = bg_color
            result["border_color"] = border_color
        else:
            result["background_color"] = None
            result["border_color"] = "black"

        return result

    def _identify_colors(self, hue_histograms: list[np.ndarray]) -> tuple[str | None, str]:
        """根据色调直方图识别底色和边框色。"""
        # 合并所有样本的直方图
        combined = np.sum(hue_histograms, axis=0)

        # 找到主色调（最大 bin）
        dominant_bin = np.argmax(combined)
        dominant_hue = dominant_bin * 5  # 每个 bin 5 度

        bg_color = self._hue_to_color_name(dominant_hue)

        # 边框色：如果底色和边框不同色，通常边框是黑色或与底色同色
        # 简化处理：有底色时默认边框为同色或黑色
        border_color = bg_color if bg_color != "yellow" else "black"

        return bg_color, border_color

    @staticmethod
    def _hue_to_color_name(hue: float) -> str:
        """将 HSV 色调值（0-180）映射到颜色名称。"""
        if hue < 10 or hue > 170:
            return "red"
        elif hue < 25:
            return "orange"
        elif hue < 35:
            return "yellow"
        elif hue < 80:
            return "green"
        elif hue < 130:
            return "blue"
        elif hue < 170:
            return "purple"
        return "red"
