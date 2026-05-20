"""页面布局分析器：检测版面布局、内容格式、版心位置。"""

import cv2
import numpy as np

from .base import BaseAnalyzer


class PageLayoutAnalyzer(BaseAnalyzer):
    """检测古籍页面的版面布局(layout)、内容格式(content_format)、版心位置(banxin_position)。

    版面布局 (layout):
    - cut_half: 已剪切的筒子页半页
    - uncut_full: 未剪切的完整筒子页
    - spread: 对开拍照/扫描

    内容格式 (content_format):
    - regular: 乌丝栏（有竖线分隔的列）
    - no_line: 无栏线（有分栏但无竖线）
    - table: 表格版式
    - illustration: 插图页
    - mixed: 文字与插图混合

    版心位置 (banxin_position): 仅 cut_half
    - left / right
    """

    name = "page_layout"

    UNCUT_ASPECT_RATIO_MIN = 1.1
    CUT_ASPECT_RATIO_MAX = 0.9

    TABLE_PAGE_RATIO = 0.3
    TABLE_INTERNAL_HLINE_MIN = 1

    CENTER_VLINE_DENSITY_THRESHOLD = 0.03
    CENTER_GAP_INK_THRESHOLD = 0.01

    def analyze(self, images: list[np.ndarray]) -> dict:
        aspect_ratios = []
        symmetry_scores = []
        table_page_count = 0
        line_counts = []
        ruling_line_found = []

        for img in images:
            h, w = img.shape[:2]
            aspect_ratios.append(w / h)
            symmetry_scores.append(self._check_center_symmetry(img))

        avg_ar = np.mean(aspect_ratios)
        avg_sym = np.mean(symmetry_scores)

        content_format = "regular"
        lines_per_page = 8
        lines_confidence = 0.3

        # ── 先检测中缝间隙（spread 的两帧之间总有墨迹接近零的列）──
        has_center_gap = False
        if avg_ar > self.CUT_ASPECT_RATIO_MAX:
            gap_results = [self._center_gap_exists(img) for img in images]
            has_center_gap = sum(gap_results) > len(gap_results) / 2

        # ── 根据宽高比 + 中缝间隙 → layout ──
        if has_center_gap:
            layout = "spread"
            confidence = min(1.0, 0.7 + (avg_ar - 1.0) * 2)
        elif avg_ar > self.UNCUT_ASPECT_RATIO_MIN:
            layout, confidence = self._classify_wide_page(images, avg_ar)
        elif avg_ar < self.CUT_ASPECT_RATIO_MAX:
            layout = "cut_half"
            confidence = min(1.0, (self.CUT_ASPECT_RATIO_MAX - avg_ar) * 5 + 0.6)

            for img in images:
                if self._is_table_page(img):
                    table_page_count += 1
            table_ratio = table_page_count / len(images) if images else 0

            if table_ratio >= self.TABLE_PAGE_RATIO:
                content_format = "table"
        else:
            layout = "uncut_full" if avg_sym > 0.7 else "cut_half"
            confidence = 0.5 + avg_sym * 0.3

        # ── 插图/混合检测（在行数检测之前）──
        if content_format not in ("table",):
            # 对 spread 页面检测右半页
            is_full_check = layout in ("uncut_full", "spread")
            illust_count = 0
            for img in images:
                if is_full_check:
                    ih, iw = img.shape[:2]
                    half = img[:, int(iw * 0.525):]
                else:
                    half = img
                if self._is_illustration_page(half):
                    illust_count += 1
            illust_ratio = illust_count / len(images) if images else 0
            if illust_ratio > 0.5:
                content_format = "illustration"

        if content_format == "table":
            mixed_count = sum(1 for img in images if self._is_mixed_page(img))
            if mixed_count / len(images) > 0.3:
                content_format = "mixed"

        # ── 行数检测（所有格式都做，table/illustration 也需要）──
        is_full = layout in ("uncut_full", "spread")
        for img in images:
            n, has_ruling = self._count_lines_with_ruling(img, is_full=is_full)
            if n is not None:
                line_counts.append(n)
            ruling_line_found.append(has_ruling)

        fallback = 9 if is_full else 8
        lines_per_page, lines_confidence = self._aggregate_lines(
            line_counts, fallback)

        # ── 无栏线检测 ──
        if content_format in ("regular",):
            ruling_ratio = sum(ruling_line_found) / len(ruling_line_found) if ruling_line_found else 1.0
            # 也检查彩色栏线（红色界行在灰度图中不明显）
            if ruling_ratio == 0:
                colored_ruling = any(
                    self._has_colored_ruling_lines(img, is_full)
                    for img in images
                )
                if colored_ruling:
                    ruling_ratio = 1.0

            if layout == "cut_half":
                if ruling_ratio == 0 and line_counts:
                    content_format = "no_line"
            # spread/uncut_full: 形态学不可靠（分辨率低），默认保持 regular

        result = {
            "layout": layout,
            "content_format": content_format,
            "lines_per_page": lines_per_page,
            "_confidence": {
                "layout": confidence,
                "lines_per_page": lines_confidence,
            },
        }

        # ── 版心位置（仅 cut_half）──
        if layout == "cut_half":
            result["banxin_position"] = self._detect_banxin_position(images)

        return result

    # ────────────────── 版心位置检测 ──────────────────

    def _detect_banxin_position(self, images: list[np.ndarray]) -> str:
        """检测版心在图片的左侧还是右侧。

        核心特征：结构化墨迹密度 (structured ink score)。
        版心侧的边缘区域有书名/鱼尾等结构化文字，行间密度变化大（std 高）。
        非版心侧的边缘可能是空白（std=0）或书脊阴影（均匀暗带，std 低）。

        使用多宽度加权投票：窄条带（4%）权重高（信号纯净），
        宽条带（8-10%）权重低（可能混入正文列）。
        """
        total_left = 0
        total_right = 0

        for img in images:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
            h, w = gray.shape
            _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

            y0 = int(h * 0.15)
            y1 = int(h * 0.85)

            for pct, weight in [(0.04, 3), (0.06, 2), (0.08, 1), (0.10, 1)]:
                strip_w = max(int(w * pct), 5)
                ls = self._structured_ink_score(bw[y0:y1, :strip_w])
                rs = self._structured_ink_score(bw[y0:y1, w - strip_w:])
                if ls > rs:
                    total_left += weight
                elif rs > ls:
                    total_right += weight

        if total_left > total_right:
            return "left"
        return "right"

    @staticmethod
    def _structured_ink_score(strip: np.ndarray) -> float:
        """计算条带的结构化墨迹分数：行间墨迹密度的标准差。

        结构化文字（版心书名/鱼尾）→ std 高（有字有空）
        均匀暗带（书脊阴影）→ std 低
        空白区域 → std = 0
        """
        row_ink = np.mean(strip, axis=1).astype(float) / 255
        if np.mean(row_ink) < 0.005:
            return 0.0
        return float(np.std(row_ink))

    # ────────────────── 插图/混合检测 ──────────────────

    def _is_illustration_page(self, img: np.ndarray) -> bool:
        """检测插图页：缺乏规则的列式文字结构。

        文字页特征：垂直投影有明显的、规则间隔的峰（列）
        插图页特征：缺乏周期性列结构，可能有大面积墨迹或不规则线条
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        roi = bw[int(h * 0.15):int(h * 0.85), int(w * 0.1):int(w * 0.9)]
        rh, rw = roi.shape

        ink_ratio = np.mean(roi) / 255

        # 高墨迹密度 — 大面积填充的插图
        if ink_ratio > 0.25:
            return True

        if ink_ratio < 0.01:
            return False

        # 检测是否有规则的列结构（文字页的核心特征）
        col_proj = np.sum(roi, axis=0).astype(np.float64) / 255
        kernel_size = max(rw // 80, 3)
        if kernel_size % 2 == 0:
            kernel_size += 1
        col_smooth = cv2.GaussianBlur(col_proj.reshape(1, -1), (kernel_size, 1), 0).flatten()

        min_peak = rh * 0.08
        min_dist = max(rw // 20, 5)
        peaks = self._find_peaks(col_smooth, min_peak, min_dist)

        # 文字页至少有 4 个列峰；插图页通常 < 3 个
        if len(peaks) < 3:
            return True

        return False

    def _is_mixed_page(self, img: np.ndarray) -> bool:
        """检测混合页面：上半部为插图、下半部为文字（或反之）。"""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        mid = h // 2
        top_half = bw[int(h * 0.1):mid, int(w * 0.1):int(w * 0.9)]
        bot_half = bw[mid:int(h * 0.9), int(w * 0.1):int(w * 0.9)]

        def has_column_structure(roi):
            col_proj = np.sum(roi, axis=0).astype(np.float64) / 255
            rh_ = roi.shape[0]
            min_peak = rh_ * 0.08
            min_dist = max(roi.shape[1] // 20, 5)
            peaks = self._find_peaks(col_proj, min_peak, min_dist)
            return len(peaks) >= 4

        top_text = has_column_structure(top_half)
        bot_text = has_column_structure(bot_half)

        # 一半有文字列结构，另一半没有 → 混合
        return top_text != bot_text

    # ────────────────── uncut_full vs spread ──────────────────

    def _classify_wide_page(self, images: list[np.ndarray],
                            avg_ar: float) -> tuple[str, float]:
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
        type_confidence = min(1.0, base_confidence + dist * 10)

        return page_type, type_confidence

    def _center_vertical_line_density(self, img: np.ndarray) -> float:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape

        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        cx0 = int(w * 0.45)
        cx1 = int(w * 0.55)
        center_bw = bw[int(h * 0.15):int(h * 0.85), cx0:cx1]
        ch = center_bw.shape[0]

        v_kernel_len = max(ch // 3, 20)
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_kernel_len))
        v_lines = cv2.morphologyEx(center_bw, cv2.MORPH_OPEN, v_kernel)

        return float(np.mean(v_lines) / 255)

    def _center_gap_exists(self, img: np.ndarray) -> bool:
        """检测图片中央是否存在纵向间隙（spread 的两帧之间的装订缝）。"""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape

        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        y0, y1 = int(h * 0.1), int(h * 0.9)
        c0, c1 = int(w * 0.40), int(w * 0.60)
        center_cols = bw[y0:y1, c0:c1]

        col_ink = np.mean(center_cols, axis=0) / 255.0
        min_ink = float(np.min(col_ink))

        return min_ink < self.CENTER_GAP_INK_THRESHOLD

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

    # ────────────────── 彩色栏线检测 ──────────────────

    def _has_colored_ruling_lines(self, img: np.ndarray, is_full: bool = False) -> bool:
        """检测彩色（红/蓝）栏线：通过饱和度通道提取。

        红色栏线在灰度 Otsu 二值化后几乎不可见，
        但在 HSV 饱和度通道中有高值。
        """
        if len(img.shape) != 3:
            return False

        if is_full:
            h, w = img.shape[:2]
            img = img[:, int(w * 0.525):]

        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h, w = img.shape[:2]

        # 高饱和度区域（S > 80）
        sat = hsv[:, :, 1]
        _, sat_mask = cv2.threshold(sat, 80, 255, cv2.THRESH_BINARY)

        y0 = int(h * 0.2)
        y1 = int(h * 0.8)
        roi = sat_mask[y0:y1, :]
        rh, rw = roi.shape

        if rh < 30 or rw < 30:
            return False

        # 形态学提取垂直线
        v_kernel_len = max(rh // 5, 15)
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_kernel_len))
        v_lines = cv2.morphologyEx(roi, cv2.MORPH_OPEN, v_kernel)

        v_proj = np.sum(v_lines, axis=0) / 255
        min_v = rh * 0.08
        min_dist = max(rw // 30, 3)
        peaks = self._find_peaks(v_proj, min_v, min_dist)

        return len(peaks) >= 3

    # ────────────────── 行数检测（带栏线判断）──────────────────

    def _count_lines_with_ruling(self, img: np.ndarray,
                                  is_full: bool = False) -> tuple[int | None, bool]:
        """检测行数，同时返回是否找到了形态学栏线。

        策略：morph 为主，proj 为 fallback。
        1. 先尝试 morph（检测栏线）
        2. morph 失败时（无栏线/低分辨率）回退到 proj（检测文字密度峰）
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape

        if is_full:
            x_start = int(w * 0.525)
            gray = gray[:, x_start:]
            h, w = gray.shape

        y0 = int(h * 0.10)
        y1 = int(h * 0.90)
        roi = gray[y0:y1, :]
        rh = y1 - y0

        _, bw = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        result = self._morph_line_count(bw, rh, w)
        has_ruling = result is not None

        if result is None:
            result = self._proj_line_count(bw, rh, w)

        return result, has_ruling

    def _morph_line_count(self, bw: np.ndarray, rh: int, w: int) -> int | None:
        """形态学方法：提取栏线竖线 → 用间距推算行数。

        多尺度扫描：从严格到宽松尝试不同 kernel 高度和 min_dist，
        取峰数最多的结果（检测到越多峰，过滤后越准确）。
        """
        best_peaks = []

        for div, min_v_ratio in [(4, 0.10), (5, 0.10), (7, 0.06), (10, 0.04)]:
            v_kernel_len = max(rh // div, 15)
            v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_kernel_len))
            v_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, v_kernel)
            v_proj = np.sum(v_lines, axis=0) / 255
            min_v = rh * min_v_ratio

            # 尝试两种 min_dist：宽松的（捕捉双边框）和标准的
            for md in [max(w // 50, 3), max(w // 30, 3)]:
                peaks = self._find_peaks(v_proj, min_v, md)
                if len(peaks) > len(best_peaks):
                    best_peaks = peaks

        if len(best_peaks) < 4:
            return None

        return self._peaks_to_line_count(best_peaks, w)

    def _proj_line_count(self, bw: np.ndarray, rh: int, w: int) -> int | None:
        """投影法 fallback：通过文字密度峰检测列数。

        仅当 morph 失败时使用（无栏线 / 低分辨率）。
        """
        col_proj = np.sum(bw, axis=0).astype(np.float64) / 255
        kernel_size = max(w // 80, 3)
        if kernel_size % 2 == 0:
            kernel_size += 1
        col_smooth = cv2.GaussianBlur(
            col_proj.reshape(1, -1), (kernel_size, 1), 0).flatten()

        min_peak = rh * 0.08
        min_dist = max(w // 20, 5)
        peaks = self._find_peaks(col_smooth, min_peak, min_dist)

        if len(peaks) < 4:
            return None

        return self._peaks_to_line_count(peaks, w)

    def _peaks_to_line_count(self, peaks: list[int], total_width: int) -> int | None:
        """从峰列表推算行数。

        策略：找出正文栏线的典型间距，排除边框/版心的异常间距，
        用正文区域宽度 / 典型间距 估算行数。

        关键：正文栏线间距是最常出现的间距范围，
        边框双线间距远小于它，版心到首栏的间距远大于它。
        """
        if len(peaks) < 3:
            return None

        n = len(peaks)
        spacings = [peaks[i + 1] - peaks[i] for i in range(n - 1)]

        # 用直方图找最常见的间距范围（正文间距的众数）
        sp_arr = np.array(spacings, dtype=float)
        # bin 宽度 = 总宽度的 3%（自适应）
        bin_w = max(total_width * 0.03, 10)
        max_sp = max(spacings)
        n_bins = max(int(max_sp / bin_w) + 1, 3)
        hist, bin_edges = np.histogram(sp_arr, bins=n_bins, range=(0, max_sp + bin_w))

        # 找最高的 bin → 正文间距的中心
        best_bin = int(np.argmax(hist))
        text_center = (bin_edges[best_bin] + bin_edges[best_bin + 1]) / 2

        # 正文间距范围：中心 ±40%
        lo = text_center * 0.6
        hi = text_center * 1.4

        # 收集所有在正文间距范围内的间距，重新计算中位数
        text_spacings = [sp for sp in spacings if lo <= sp <= hi]
        if len(text_spacings) < 2:
            return None
        text_spacing = float(np.median(text_spacings))

        # 找正文区域的边界（第一个和最后一个正文间距对应的峰）
        first_idx = None
        last_idx = None
        for i, sp in enumerate(spacings):
            if lo <= sp <= hi:
                if first_idx is None:
                    first_idx = i
                last_idx = i + 1  # 右峰索引

        if first_idx is None:
            return None

        content_width = peaks[last_idx] - peaks[first_idx]
        estimated = round(content_width / text_spacing)

        if 3 <= estimated <= 15:
            return estimated

        return None

    def _aggregate_lines(self, line_counts: list[int],
                         fallback: int) -> tuple[int, float]:
        if not line_counts:
            return fallback, 0.3

        from collections import Counter
        counter = Counter(line_counts)
        val, count = counter.most_common(1)[0]
        confidence = count / len(line_counts)
        if 4 <= val <= 15:
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
