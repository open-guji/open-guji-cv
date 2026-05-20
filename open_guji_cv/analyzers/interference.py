"""干扰项分析器：检测书脊阴影、页边距等。"""

import cv2
import numpy as np

from .base import BaseAnalyzer


class InterferenceAnalyzer(BaseAnalyzer):
    """检测古籍图像中的干扰项。

    检测项目：
    - spine_shadow: 书脊阴影（页面侧边的纵向暗条纹）
    - margin: 页边距（内容区外的均匀边距区域，白色或黑色）
    同时输出 margin_color（white/black/other/null）。
    """

    name = "interference"

    def analyze(self, images: list[np.ndarray]) -> dict:
        interferences = set()
        confidences = {}

        spine_scores = [self._detect_spine_shadow(img) for img in images]
        margin_results = [self._detect_margin(img) for img in images]

        avg_spine = np.mean(spine_scores)

        margin_scores = [r[0] for r in margin_results]
        margin_colors = [r[1] for r in margin_results if r[0] > 0.5]
        avg_margin = np.mean(margin_scores)

        if avg_spine > 0.5:
            interferences.add("spine_shadow")
            confidences["spine_shadow"] = avg_spine

        margin_color = None
        if avg_margin > 0.5:
            interferences.add("margin")
            confidences["margin"] = avg_margin
            # 取 margin_color 众数
            if margin_colors:
                from collections import Counter
                margin_color = Counter(margin_colors).most_common(1)[0][0]

        return {
            "interferences": sorted(interferences),
            "margin_color": margin_color,
            "_confidence": confidences,
        }

    # ── 书脊阴影检测参数 ──
    N_BANDS = 5
    DARK_THRESHOLD = 25
    MIN_DARK_WIDTH_RATIO = 0.05
    MAX_CENTER_DRIFT = 0.20

    def _detect_spine_shadow(self, img: np.ndarray) -> float:
        """检测书脊阴影：页面左/右侧边缘从顶到底贯穿的纵向暗带。"""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape

        edge_width = max(w // 7, 20)
        max_score = 0.0

        for side_strip in [gray[:, :edge_width], gray[:, w - edge_width:]]:
            score = self._score_spine_strip(side_strip, edge_width)
            max_score = max(max_score, score)

        return max_score

    def _score_spine_strip(self, strip: np.ndarray, edge_width: int) -> float:
        """对单侧条带做分段暗带检测，返回书脊阴影置信度。"""
        h = strip.shape[0]
        band_h = h // self.N_BANDS
        if band_h < 10:
            return 0.0

        dark_centers = []

        for i in range(self.N_BANDS):
            y0 = i * band_h
            y1 = h if i == self.N_BANDS - 1 else (i + 1) * band_h
            band = strip[y0:y1, :]

            col_means = np.mean(band, axis=0)
            center = self._find_dark_band_center(col_means, edge_width)
            dark_centers.append(center)

        has_top = dark_centers[0] is not None
        has_bottom = dark_centers[-1] is not None
        n_detected = sum(1 for c in dark_centers if c is not None)

        if not has_top or not has_bottom:
            return 0.0
        if n_detected < 4:
            return 0.0

        detected = [c for c in dark_centers if c is not None]
        center_spread = max(detected) - min(detected)
        if center_spread > edge_width * self.MAX_CENTER_DRIFT:
            return 0.0

        return n_detected / self.N_BANDS

    def _find_dark_band_center(self, col_means: np.ndarray,
                               edge_width: int) -> int | None:
        """在一段的列均值曲线中找到连续暗带的中心位置。"""
        baseline = np.median(col_means)
        dark_mask = col_means < (baseline - self.DARK_THRESHOLD)

        min_width = max(int(edge_width * self.MIN_DARK_WIDTH_RATIO), 2)

        best_start, best_len = -1, 0
        cur_start, cur_len = -1, 0

        for j, is_dark in enumerate(dark_mask):
            if is_dark:
                if cur_len == 0:
                    cur_start = j
                cur_len += 1
            else:
                if cur_len > best_len:
                    best_start, best_len = cur_start, cur_len
                cur_len = 0
        if cur_len > best_len:
            best_start, best_len = cur_start, cur_len

        if best_len >= min_width:
            return best_start + best_len // 2
        return None

    def _detect_margin(self, img: np.ndarray) -> tuple[float, str | None]:
        """检测页边距：图像边缘的均匀区域（白色或黑色）。

        Returns:
            (confidence, color) — confidence 0~1, color "white"/"black"/"other"/None
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape

        margin = max(min(h, w) // 15, 10)

        edges = [
            gray[:margin, :],           # 上
            gray[h - margin:, :],       # 下
            gray[:, :margin],           # 左
            gray[:, w - margin:],       # 右
        ]
        edge_means = [float(np.mean(e)) for e in edges]
        edge_stds = [float(np.std(e)) for e in edges]

        center = gray[h // 4: 3 * h // 4, w // 4: 3 * w // 4]
        center_mean = float(np.mean(center))

        avg_edge = np.mean(edge_means)
        avg_std = np.mean(edge_stds)

        # 白色页边距：边缘比中心亮很多
        bright_diff = avg_edge - center_mean
        if bright_diff > 30:
            conf = min(1.0, bright_diff / 60.0)
            return conf, "white"

        # 黑色页边距：边缘比中心暗很多且均匀
        dark_diff = center_mean - avg_edge
        if dark_diff > 30 and avg_std < 40:
            conf = min(1.0, dark_diff / 60.0)
            return conf, "black"

        # 边缘亮度与中心差异不大但标准差低（均匀的非内容区域）
        if abs(avg_edge - center_mean) > 15 and avg_std < 30:
            conf = min(0.8, abs(avg_edge - center_mean) / 40.0)
            return conf, "other"

        return 0.0, None
