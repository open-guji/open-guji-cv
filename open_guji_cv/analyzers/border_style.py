"""边框分析器：检测边框样式（单/双层）和磨损程度。"""

import cv2
import numpy as np

from .base import BaseAnalyzer


class BorderAnalyzer(BaseAnalyzer):
    """检测古籍图像的边框特征。

    检测项：
    - border_style: "double"（双层：外粗内细）/ "single"（单层）
    - border_wear: "light" / "medium" / "heavy"

    方法：
    - 边框样式：在四条边取垂直于边框方向的截面灰度曲线，
      双层边框会出现两个暗峰夹一个亮谷的特征。
    - 磨损程度：检测边框线的连续性（断裂程度）。
    """

    name = "border_style"

    # 边框检测区域：距图像边缘的搜索范围（占图像尺寸的比例）
    BORDER_SEARCH_RATIO = 0.15

    # 双层检测参数
    DOUBLE_VALLEY_MIN_DEPTH = 10    # 两层之间亮谷的最小深度（灰度值差）
    DOUBLE_MIN_GAP = 2              # 两条线之间最小间距（像素）

    # 磨损检测参数
    WEAR_COVERAGE_HEAVY = 0.4       # 覆盖率 < 40% → heavy
    WEAR_COVERAGE_MEDIUM = 0.7      # 覆盖率 < 70% → medium，否则 light

    def analyze(self, images: list[np.ndarray]) -> dict:
        double_votes = 0
        single_votes = 0
        wear_scores = []  # 每张图的覆盖率

        for img in images:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img

            is_double, profiles = self._detect_border_style(gray)
            if is_double:
                double_votes += 1
            else:
                single_votes += 1

            coverage = self._measure_border_coverage(gray)
            wear_scores.append(coverage)

        # 边框样式：多数投票
        total = double_votes + single_votes
        if total == 0:
            border_style = "double"
            style_confidence = 0.3
        else:
            border_style = "double" if double_votes >= single_votes else "single"
            style_confidence = max(double_votes, single_votes) / total

        # 磨损程度
        avg_coverage = np.mean(wear_scores) if wear_scores else 0.5
        if avg_coverage < self.WEAR_COVERAGE_HEAVY:
            border_wear = "heavy"
        elif avg_coverage < self.WEAR_COVERAGE_MEDIUM:
            border_wear = "medium"
        else:
            border_wear = "light"

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

    def _detect_border_style(self, gray: np.ndarray) -> tuple[bool, list]:
        """检测边框是单层还是双层。

        在图像四条边各取一组垂直截面，分析灰度曲线：
        - 双层：两个暗峰夹一个亮谷
        - 单层：只有一个暗峰

        Returns:
            (is_double, profiles) - 是否双层，以及各边的灰度截面
        """
        h, w = gray.shape
        search_w = int(min(h, w) * self.BORDER_SEARCH_RATIO)
        if search_w < 10:
            return False, []

        double_count = 0
        profiles = []

        # 四条边的截面采样
        # 取多个采样位置，取中值轮廓减少噪声
        sides = self._sample_border_profiles(gray, search_w)

        for profile in sides:
            profiles.append(profile)
            if self._profile_is_double(profile):
                double_count += 1

        # 至少 1/4 条边检测到双层（因为磨损可能只有部分边可见双层）
        return double_count >= 1, profiles

    def _sample_border_profiles(self, gray: np.ndarray,
                                search_w: int) -> list[np.ndarray]:
        """在四条边各采样多条垂直于边框方向的灰度曲线，取中值。

        Returns:
            四条边的中值灰度曲线列表 [left, right, top, bottom]
        """
        h, w = gray.shape
        n_samples = 15  # 每边取 15 个采样点
        profiles = []

        # 左边：从左向右的水平截面
        sample_ys = np.linspace(h * 0.2, h * 0.8, n_samples).astype(int)
        strips = np.array([gray[y, :search_w].astype(np.float64) for y in sample_ys])
        profiles.append(np.median(strips, axis=0))

        # 右边：从右向左
        strips = np.array([gray[y, w - search_w:][::-1].astype(np.float64) for y in sample_ys])
        profiles.append(np.median(strips, axis=0))

        # 上边：从上向下的垂直截面
        sample_xs = np.linspace(w * 0.2, w * 0.8, n_samples).astype(int)
        strips = np.array([gray[:search_w, x].astype(np.float64) for x in sample_xs])
        profiles.append(np.median(strips, axis=0))

        # 下边：从下向上
        strips = np.array([gray[h - search_w:, x][::-1].astype(np.float64) for x in sample_xs])
        profiles.append(np.median(strips, axis=0))

        return profiles

    def _profile_is_double(self, profile: np.ndarray) -> bool:
        """分析灰度截面曲线是否呈现双层边框特征。

        双层边框特征：从外向内，先遇到外层暗线（粗），然后一段亮区，
        再遇到内层暗线（细）。

        策略：
        1. 找到第一个暗峰（外层边框）
        2. 跳过外层后，检查是否还有第二个暗峰（内层边框），中间有亮谷
        """
        n = len(profile)
        if n < 15:
            return False

        # 取背景亮度参考（靠近内容区域的一段）
        bg_level = np.mean(profile[int(n * 0.6):])
        dark_threshold = bg_level - 30  # 暗于背景 30+ 灰度视为边框线

        # 找所有暗区段
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

        # 检查前两个暗区之间是否有亮谷
        r1_end = dark_regions[0][1]
        r2_start = dark_regions[1][0]
        gap = r2_start - r1_end

        if gap < self.DOUBLE_MIN_GAP:
            return False

        # 亮谷的亮度应该接近背景
        valley = profile[r1_end:r2_start]
        valley_brightness = np.mean(valley)
        dark_level = np.min(profile[dark_regions[0][0]:dark_regions[0][1]])
        valley_depth = valley_brightness - dark_level

        return valley_depth >= self.DOUBLE_VALLEY_MIN_DEPTH

    # ────────────────── 磨损程度检测 ──────────────────

    def _measure_border_coverage(self, gray: np.ndarray) -> float:
        """测量边框线的连续性（覆盖率）。

        方法：用形态学提取水平/垂直长线，在边框区域测量线条覆盖比例。
        覆盖率高 → 磨损轻；覆盖率低 → 磨损重。

        Returns:
            覆盖率 0~1
        """
        h, w = gray.shape

        # 二值化
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # 提取垂直长线（用于检测左右边框）
        v_kernel_len = max(h // 6, 30)
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_kernel_len))
        v_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, v_kernel)

        # 提取水平长线（用于检测上下边框）
        h_kernel_len = max(w // 6, 30)
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (h_kernel_len, 1))
        h_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, h_kernel)

        search = int(min(h, w) * self.BORDER_SEARCH_RATIO)
        coverages = []

        # 左边框覆盖率：左侧条带中垂直线的高度覆盖比
        left_strip = v_lines[:, :search]
        left_proj = np.any(left_strip > 0, axis=1)
        coverages.append(np.mean(left_proj))

        # 右边框
        right_strip = v_lines[:, w - search:]
        right_proj = np.any(right_strip > 0, axis=1)
        coverages.append(np.mean(right_proj))

        # 上边框
        top_strip = h_lines[:search, :]
        top_proj = np.any(top_strip > 0, axis=0)
        coverages.append(np.mean(top_proj))

        # 下边框
        bot_strip = h_lines[h - search:, :]
        bot_proj = np.any(bot_strip > 0, axis=0)
        coverages.append(np.mean(bot_proj))

        return float(np.mean(coverages)) if coverages else 0.5
