"""边框分析器：检测边框样式（单/双/上下单左右双）和磨损程度。"""

import cv2
import numpy as np

from .base import BaseAnalyzer


class BorderAnalyzer(BaseAnalyzer):
    """检测古籍图像的边框特征。

    检测项：
    - border_style: "double" / "single" / "hsingle_vdouble"
    - border_wear: "none" / "light" / "medium" / "heavy"
    """

    name = "border_style"

    BORDER_SEARCH_RATIO = 0.15

    DOUBLE_VALLEY_MIN_DEPTH = 10
    DOUBLE_MIN_GAP = 2

    WEAR_COVERAGE_NONE = 0.95
    WEAR_COVERAGE_HEAVY = 0.4
    WEAR_COVERAGE_MEDIUM = 0.7

    def analyze(self, images: list[np.ndarray]) -> dict:
        # 每张图的四条边 double 检测结果: [left, right, top, bottom]
        all_side_results = []
        wear_scores = []

        for img in images:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img

            side_doubles = self._detect_border_style_per_side(gray)
            all_side_results.append(side_doubles)

            coverage = self._measure_border_coverage(gray)
            wear_scores.append(coverage)

        # 汇总：分别统计垂直边（左右）和水平边（上下）的 double 票数
        v_double = 0  # left + right
        v_total = 0
        h_double = 0  # top + bottom
        h_total = 0

        for sides in all_side_results:
            # sides = [left_is_double, right_is_double, top_is_double, bottom_is_double]
            for i, is_d in enumerate(sides):
                if is_d is None:
                    continue
                if i < 2:  # left, right = vertical borders
                    v_total += 1
                    if is_d:
                        v_double += 1
                else:  # top, bottom = horizontal borders
                    h_total += 1
                    if is_d:
                        h_double += 1

        v_ratio = v_double / v_total if v_total > 0 else 0
        h_ratio = h_double / h_total if h_total > 0 else 0

        # 判断 border_style
        if v_ratio >= 0.4 and h_ratio < 0.3:
            border_style = "hsingle_vdouble"
        elif v_ratio >= 0.3 or h_ratio >= 0.3:
            border_style = "double"
        else:
            border_style = "single"

        total = v_total + h_total
        all_double = v_double + h_double
        style_confidence = max(all_double, total - all_double) / total if total > 0 else 0.3

        # 磨损程度
        avg_coverage = np.mean(wear_scores) if wear_scores else 0.5
        if avg_coverage >= self.WEAR_COVERAGE_NONE:
            border_wear = "none"
        elif avg_coverage >= self.WEAR_COVERAGE_MEDIUM:
            border_wear = "light"
        elif avg_coverage >= self.WEAR_COVERAGE_HEAVY:
            border_wear = "medium"
        else:
            border_wear = "heavy"

        wear_confidence = min(1.0, 0.5 + abs(avg_coverage - 0.55) * 2)

        return {
            "border_style": border_style,
            "border_wear": border_wear,
            "_confidence": {
                "border_style": round(style_confidence, 2),
                "border_wear": round(wear_confidence, 2),
            },
        }

    # ────────────────── 边框样式检测 ──────────────────

    def _detect_border_style_per_side(self, gray: np.ndarray) -> list[bool | None]:
        """检测四条边各自是否为双层。

        Returns:
            [left, right, top, bottom] — True=double, False=single, None=无法判断
        """
        h, w = gray.shape
        search_w = int(min(h, w) * self.BORDER_SEARCH_RATIO)
        if search_w < 10:
            return [None, None, None, None]

        sides = self._sample_border_profiles(gray, search_w)
        results = []
        for profile in sides:
            if profile is None or len(profile) < 15:
                results.append(None)
            else:
                results.append(self._profile_is_double(profile))
        return results

    def _sample_border_profiles(self, gray: np.ndarray,
                                search_w: int) -> list[np.ndarray]:
        """在四条边各采样多条垂直于边框方向的灰度曲线，取中值。

        Returns:
            [left, right, top, bottom] 的中值灰度曲线
        """
        h, w = gray.shape
        n_samples = 15
        profiles = []

        sample_ys = np.linspace(h * 0.2, h * 0.8, n_samples).astype(int)
        strips = np.array([gray[y, :search_w].astype(np.float64) for y in sample_ys])
        profiles.append(np.median(strips, axis=0))

        strips = np.array([gray[y, w - search_w:][::-1].astype(np.float64) for y in sample_ys])
        profiles.append(np.median(strips, axis=0))

        sample_xs = np.linspace(w * 0.2, w * 0.8, n_samples).astype(int)
        strips = np.array([gray[:search_w, x].astype(np.float64) for x in sample_xs])
        profiles.append(np.median(strips, axis=0))

        strips = np.array([gray[h - search_w:, x][::-1].astype(np.float64) for x in sample_xs])
        profiles.append(np.median(strips, axis=0))

        return profiles

    def _profile_is_double(self, profile: np.ndarray) -> bool:
        """分析灰度截面曲线是否呈现双层边框特征。"""
        n = len(profile)
        if n < 15:
            return False

        bg_level = np.mean(profile[int(n * 0.6):])
        dark_threshold = bg_level - 30

        dark_regions = []
        in_dark = False
        start = 0

        for i, v in enumerate(profile):
            if v < dark_threshold:
                if not in_dark:
                    start = i
                    in_dark = True
            else:
                if in_dark:
                    dark_regions.append((start, i))
                    in_dark = False
        if in_dark:
            dark_regions.append((start, n))

        if len(dark_regions) < 2:
            return False

        r1_end = dark_regions[0][1]
        r2_start = dark_regions[1][0]
        gap = r2_start - r1_end

        if gap < self.DOUBLE_MIN_GAP:
            return False

        valley = profile[r1_end:r2_start]
        valley_brightness = np.mean(valley)
        dark_level = np.min(profile[dark_regions[0][0]:dark_regions[0][1]])
        valley_depth = valley_brightness - dark_level

        return valley_depth >= self.DOUBLE_VALLEY_MIN_DEPTH

    # ────────────────── 磨损程度检测 ──────────────────

    def _measure_border_coverage(self, gray: np.ndarray) -> float:
        """测量边框线的连续性（覆盖率）。"""
        h, w = gray.shape

        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        v_kernel_len = max(h // 6, 30)
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_kernel_len))
        v_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, v_kernel)

        h_kernel_len = max(w // 6, 30)
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (h_kernel_len, 1))
        h_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, h_kernel)

        search = int(min(h, w) * self.BORDER_SEARCH_RATIO)
        coverages = []

        left_strip = v_lines[:, :search]
        left_proj = np.any(left_strip > 0, axis=1)
        coverages.append(np.mean(left_proj))

        right_strip = v_lines[:, w - search:]
        right_proj = np.any(right_strip > 0, axis=1)
        coverages.append(np.mean(right_proj))

        top_strip = h_lines[:search, :]
        top_proj = np.any(top_strip > 0, axis=0)
        coverages.append(np.mean(top_proj))

        bot_strip = h_lines[h - search:, :]
        bot_proj = np.any(bot_strip > 0, axis=0)
        coverages.append(np.mean(bot_proj))

        return float(np.mean(coverages)) if coverages else 0.5
