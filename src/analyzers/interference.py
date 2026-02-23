"""干扰项分析器：检测书脊阴影、白色页边距、污渍等。"""

import cv2
import numpy as np

from .base import BaseAnalyzer


class InterferenceAnalyzer(BaseAnalyzer):
    """检测古籍图像中的干扰项。

    检测项目：
    - spine_shadow: 书脊阴影（页面侧边的纵向暗条纹）
    - white_margin: 白色页边距（内容区外的高亮度空白）
    - stains: 污渍（背景上的异常色块）
    - page_number: 页码（页面底部的数字）
    """

    name = "interference"

    def analyze(self, images: list[np.ndarray]) -> dict:
        interferences = set()
        confidences = {}

        # 检测各类干扰项
        spine_scores = [self._detect_spine_shadow(img) for img in images]
        margin_scores = [self._detect_white_margin(img) for img in images]
        stain_scores = [self._detect_stains(img) for img in images]

        avg_spine = np.mean(spine_scores)
        avg_margin = np.mean(margin_scores)
        avg_stain = np.mean(stain_scores)

        if avg_spine > 0.5:
            interferences.add("spine_shadow")
            confidences["spine_shadow"] = avg_spine

        if avg_margin > 0.5:
            interferences.add("white_margin")
            confidences["white_margin"] = avg_margin

        if avg_stain > 0.5:
            interferences.add("stains")
            confidences["stains"] = avg_stain

        return {
            "interferences": sorted(interferences),
            "_confidence": confidences,
        }

    # ── 书脊阴影检测参数 ──
    N_BANDS = 5               # 垂直方向分段数
    DARK_THRESHOLD = 25       # 暗带相对于基线的最小下降灰度
    MIN_DARK_WIDTH_RATIO = 0.05  # 暗带最小宽度占条带宽度的比例
    MAX_CENTER_DRIFT = 0.20   # 暗带中心在各段间的最大偏移（占 edge_width）

    def _detect_spine_shadow(self, img: np.ndarray) -> float:
        """检测书脊阴影：页面左/右侧边缘从顶到底贯穿的纵向暗带。

        核心思路：将边缘条带沿垂直方向分成 N_BANDS 段，在每段内独立检测暗带。
        书脊阴影的特征是从顶贯穿到底，因此要求顶部段和底部段都存在暗带。
        而边框/扫描边缘只在中间段有竖线，上下端是空白，不会被误判。

        Returns:
            置信度 0~1。
        """
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

        dark_centers = []  # 每段暗带的中心列位置，None 表示该段无暗带

        for i in range(self.N_BANDS):
            y0 = i * band_h
            y1 = h if i == self.N_BANDS - 1 else (i + 1) * band_h
            band = strip[y0:y1, :]

            col_means = np.mean(band, axis=0)
            center = self._find_dark_band_center(col_means, edge_width)
            dark_centers.append(center)

        # 贯穿性判断
        has_top = dark_centers[0] is not None
        has_bottom = dark_centers[-1] is not None
        n_detected = sum(1 for c in dark_centers if c is not None)

        if not has_top or not has_bottom:
            # 顶部或底部无暗带 → 不是书脊阴影
            return 0.0

        if n_detected < 4:
            # 至少 4/5 段有暗带才算贯穿
            return 0.0

        # 检查暗带位置一致性
        detected = [c for c in dark_centers if c is not None]
        center_spread = max(detected) - min(detected)
        if center_spread > edge_width * self.MAX_CENTER_DRIFT:
            return 0.0

        return n_detected / self.N_BANDS

    def _find_dark_band_center(self, col_means: np.ndarray,
                               edge_width: int) -> int | None:
        """在一段的列均值曲线中找到连续暗带的中心位置。

        Returns:
            暗带中心列索引，或 None（未找到）。
        """
        baseline = np.median(col_means)
        dark_mask = col_means < (baseline - self.DARK_THRESHOLD)

        min_width = max(int(edge_width * self.MIN_DARK_WIDTH_RATIO), 2)

        # 找最长的连续暗区
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

    def _detect_white_margin(self, img: np.ndarray) -> float:
        """检测白色页边距：图像边缘的高亮度均匀区域。

        方法：检查图像四个边缘条带的亮度是否明显高于中心区域。

        Returns:
            置信度 0~1。
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape

        # 边缘条带宽度
        margin = max(min(h, w) // 15, 10)

        # 四个边缘的平均亮度
        edges = [
            gray[:margin, :],           # 上
            gray[h - margin:, :],       # 下
            gray[:, :margin],           # 左
            gray[:, w - margin:],       # 右
        ]
        edge_means = [np.mean(e) for e in edges]

        # 中心区域平均亮度
        center = gray[h // 4: 3 * h // 4, w // 4: 3 * w // 4]
        center_mean = np.mean(center)

        # 如果边缘比中心亮很多（比如 > 30），说明有白色页边距
        avg_edge = np.mean(edge_means)
        brightness_diff = avg_edge - center_mean

        if brightness_diff > 30:
            return min(1.0, brightness_diff / 60.0)
        return 0.0

    def _detect_stains(self, img: np.ndarray) -> float:
        """检测污渍：背景上的异常色块。

        方法：在灰度图上检测局部区域与全局均值的偏差。

        Returns:
            置信度 0~1。
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img

        # 用大核高斯模糊来估计背景
        bg = cv2.GaussianBlur(gray, (51, 51), 0)

        # 计算与背景的差异
        diff = cv2.absdiff(gray, bg)

        # 对差异图做阈值：显著偏离背景的区域
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)

        # 排除文字区域（文字通常在有结构的地方，而污渍是随机分布的）
        # 简化：直接看异常像素比例
        anomaly_ratio = np.count_nonzero(thresh) / thresh.size

        # 污渍通常占 1%~10% 的面积
        if 0.01 < anomaly_ratio < 0.15:
            return min(1.0, anomaly_ratio * 10)
        return 0.0
