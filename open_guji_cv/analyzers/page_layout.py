"""页面布局分析器：检测已剪切/未剪切/对开/表格、行数等。"""

import cv2
import numpy as np

from .base import BaseAnalyzer


class PageLayoutAnalyzer(BaseAnalyzer):
    """检测古籍页面的布局类型和行数。

    页面类型：
    - cut_half: 已剪切的筒子页半页（竖向单页）
    - uncut_full: 未剪切的完整筒子页，上下边框贯穿全宽，中间是版心
    - spread: 对开拍照/扫描，两个独立边框并排，中间是书脊
    - table: 表格版式（有内部横线网格）

    判断逻辑：
    1. 宽高比 < 0.9 → cut_half 或 table
    2. 宽高比 > 1.1 → uncut_full 或 spread（通过边框连续性区分）
    3. 模糊地带 → 用对称性辅助
    """

    name = "page_layout"

    UNCUT_ASPECT_RATIO_MIN = 1.1
    CUT_ASPECT_RATIO_MAX = 0.9

    TABLE_PAGE_RATIO = 0.3
    TABLE_INTERNAL_HLINE_MIN = 1

    # uncut_full vs spread 区分
    # spread 的中央区域有两个页框的粗边框线（垂直线密度高）
    # uncut_full 的中央是版心（细界行 + 文字，垂直线密度低）
    CENTER_VLINE_DENSITY_THRESHOLD = 0.03

    def analyze(self, images: list[np.ndarray]) -> dict:
        aspect_ratios = []
        symmetry_scores = []
        table_page_count = 0
        line_counts = []

        for img in images:
            h, w = img.shape[:2]
            aspect_ratios.append(w / h)
            symmetry_scores.append(self._check_center_symmetry(img))

        avg_ar = np.mean(aspect_ratios)
        avg_sym = np.mean(symmetry_scores)

        # ── 先判断宽高比 ──
        if avg_ar > self.UNCUT_ASPECT_RATIO_MIN:
            # 横向页面：区分 uncut_full 和 spread
            page_type, confidence = self._classify_wide_page(images, avg_ar)
        elif avg_ar < self.CUT_ASPECT_RATIO_MAX:
            # 竖向页面：可能是 cut_half 或 table
            for img in images:
                if self._is_table_page(img):
                    table_page_count += 1
            table_ratio = table_page_count / len(images) if images else 0

            if table_ratio >= self.TABLE_PAGE_RATIO:
                page_type = "table"
                confidence = min(1.0, table_ratio + 0.3)
                lines_per_page = 0
                lines_confidence = 0.0
            else:
                page_type = "cut_half"
                confidence = min(1.0, (self.CUT_ASPECT_RATIO_MAX - avg_ar) * 5 + 0.6)
        else:
            page_type = "uncut_full" if avg_sym > 0.7 else "cut_half"
            confidence = 0.5 + avg_sym * 0.3

        # ── 行数检测（非表格时）──
        if page_type != "table":
            is_full = page_type in ("uncut_full", "spread")
            for img in images:
                n = self._count_lines(img, is_full=is_full)
                if n is not None:
                    line_counts.append(n)

            fallback = 9 if is_full else 8
            lines_per_page, lines_confidence = self._aggregate_lines(
                line_counts, fallback)

        return {
            "page_type": page_type,
            "lines_per_page": lines_per_page,
            "_confidence": {
                "page_type": confidence,
                "lines_per_page": lines_confidence,
            },
        }

    # ────────────────── uncut_full vs spread ──────────────────

    def _classify_wide_page(self, images: list[np.ndarray],
                            avg_ar: float) -> tuple[str, float]:
        """区分 uncut_full（筒子页）和 spread（对开拍照）。

        关键区别：
        - uncut_full: 中央是版心（鱼尾+书名文字），没有粗垂直边框线
        - spread: 中央是两个独立页框的内侧边框，有明显的粗垂直线

        方法：在中央 10% 宽度条带中，用形态学提取长垂直线，
        测量其密度。密度高 → spread，密度低 → uncut_full。
        """
        densities = []

        for img in images:
            density = self._center_vertical_line_density(img)
            densities.append(density)

        avg_density = np.mean(densities)

        if avg_density >= self.CENTER_VLINE_DENSITY_THRESHOLD:
            page_type = "spread"
        else:
            page_type = "uncut_full"

        base_confidence = min(1.0, (avg_ar - self.UNCUT_ASPECT_RATIO_MIN) * 5 + 0.6)
        dist = abs(avg_density - self.CENTER_VLINE_DENSITY_THRESHOLD)
        # 距离阈值越远，置信度越高
        type_confidence = min(1.0, base_confidence + dist * 10)

        return page_type, type_confidence

    def _center_vertical_line_density(self, img: np.ndarray) -> float:
        """测量图像中央区域的垂直线密度。

        在中央 10% 宽度、排除天头地脚后的区域中，
        用形态学提取长垂直线，计算像素密度。

        Returns:
            垂直线密度 0~1。spread 页面通常 > 0.06，
            uncut_full 页面通常 < 0.005。
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape

        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # 中央条带（10% 宽度），排除天头地脚（上下 15%）
        cx0 = int(w * 0.45)
        cx1 = int(w * 0.55)
        center_bw = bw[int(h * 0.15):int(h * 0.85), cx0:cx1]
        ch = center_bw.shape[0]

        # 提取长垂直线
        v_kernel_len = max(ch // 3, 20)
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_kernel_len))
        v_lines = cv2.morphologyEx(center_bw, cv2.MORPH_OPEN, v_kernel)

        return float(np.mean(v_lines) / 255)

    # ────────────────── 中线对称性 ──────────────────

    def _check_center_symmetry(self, img: np.ndarray) -> float:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape
        strip_w = max(w // 20, 5)
        cx = w // 2
        left = gray[:, cx - strip_w: cx].astype(np.float32)
        right = gray[:, cx: cx + strip_w].astype(np.float32)
        diff = np.abs(left - np.flip(right, axis=1))
        return float(1.0 - np.mean(diff) / 255.0)

    # ────────────────── 表格检测 ──────────────────

    def _is_table_page(self, img: np.ndarray) -> bool:
        """单页是否为表格页面：内容区内部有水平线。"""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape

        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        h_kernel_len = max(w // 15, 20)
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (h_kernel_len, 1))
        h_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, h_kernel)

        h_proj = np.sum(h_lines, axis=1) / 255
        min_height = w * 0.1
        min_dist = max(h // 40, 5)
        peaks = self._find_peaks(h_proj, min_height, min_dist)

        internal = [p for p in peaks if h * 0.25 < p < h * 0.75]
        return len(internal) >= self.TABLE_INTERNAL_HLINE_MIN

    # ────────────────── 行数检测 ──────────────────

    def _count_lines(self, img: np.ndarray, is_full: bool = False) -> int | None:
        """基于间距规律性检测行数。"""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape

        if is_full:
            # 取右半页（避开版心/书脊）
            x_start = int(w * 0.525)
            gray = gray[:, x_start:]
            h, w = gray.shape

        y0 = int(h * 0.2)
        y1 = int(h * 0.8)
        roi = gray[y0:y1, :]
        rh = y1 - y0

        _, bw = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        result_a = self._morph_line_count(bw, rh, w)
        result_b = self._proj_line_count(bw, rh, w)

        if result_a is not None and result_b is not None:
            if abs(result_a - result_b) <= 2:
                return result_a
            for v in [result_a, result_b]:
                if 6 <= v <= 12:
                    return v
            return result_a

        return result_a or result_b

    def _morph_line_count(self, bw: np.ndarray, rh: int, w: int) -> int | None:
        """形态学方法：提取界行 → 用间距推算行数。"""
        for div in [4, 5]:
            v_kernel_len = max(rh // div, 20)
            v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_kernel_len))
            v_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, v_kernel)
            v_proj = np.sum(v_lines, axis=0) / 255

            min_v = rh * 0.1
            min_dist = max(w // 30, 3)
            peaks = self._find_peaks(v_proj, min_v, min_dist)

            if len(peaks) >= 3:
                return self._spacing_based_count(peaks, w)

        return None

    def _proj_line_count(self, bw: np.ndarray, rh: int, w: int) -> int | None:
        """投影法：通过垂直投影的峰值间距推算行数。"""
        col_proj = np.sum(bw, axis=0).astype(np.float64) / 255
        kernel_size = max(w // 80, 3)
        if kernel_size % 2 == 0:
            kernel_size += 1
        col_smooth = cv2.GaussianBlur(
            col_proj.reshape(1, -1), (kernel_size, 1), 0).flatten()

        min_peak = rh * 0.08
        min_dist = max(w // 20, 5)
        peaks = self._find_peaks(col_smooth, min_peak, min_dist)

        if len(peaks) >= 4:
            return self._spacing_based_count(peaks, w)

        return None

    def _spacing_based_count(self, peaks: list[int], total_width: int) -> int | None:
        """基于峰值间距推算行数。"""
        if len(peaks) < 2:
            return None

        spacings = [peaks[i + 1] - peaks[i] for i in range(len(peaks) - 1)]
        if not spacings:
            return None

        median_spacing = np.median(spacings)
        if median_spacing < 5:
            return None

        content_width = peaks[-1] - peaks[0]
        estimated = round(content_width / median_spacing)

        if 5 <= estimated <= 15:
            return estimated

        return None

    def _aggregate_lines(self, line_counts: list[int],
                         fallback: int) -> tuple[int, float]:
        """汇总结果，取众数。"""
        if not line_counts:
            return fallback, 0.3

        from collections import Counter
        counter = Counter(line_counts)
        val, count = counter.most_common(1)[0]
        confidence = count / len(line_counts)
        if 6 <= val <= 12:
            confidence = min(1.0, confidence + 0.2)

        return val, round(confidence, 2)

    # ────────────────── 工具方法 ──────────────────

    @staticmethod
    def _find_peaks(signal: np.ndarray, min_height: float,
                    min_distance: int) -> list[int]:
        n = len(signal)
        if n < 3:
            return []

        peaks = []
        for i in range(1, n - 1):
            if signal[i] >= min_height:
                left = max(0, i - min_distance)
                right = min(n, i + min_distance)
                if signal[i] == np.max(signal[left:right]):
                    peaks.append(i)

        if not peaks:
            return []

        merged = [peaks[0]]
        for p in peaks[1:]:
            if p - merged[-1] >= min_distance:
                merged.append(p)

        return merged
