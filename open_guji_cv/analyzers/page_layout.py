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
        """检测行数，同时返回是否找到了形态学栏线。"""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape

        if is_full:
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
        result_c = self._cc_line_count(bw, rh, w) if w < 800 else None  # CC 仅低分辨率

        has_ruling = result_a is not None

        # 收集所有有效结果
        candidates = []
        if result_a is not None:
            candidates.append(('morph', result_a))
        if result_b is not None:
            candidates.append(('proj', result_b))
        if result_c is not None:
            candidates.append(('cc', result_c))

        if not candidates:
            return None, has_ruling

        if len(candidates) == 1:
            return candidates[0][1], has_ruling

        values = [v for _, v in candidates]

        # 如果有两个或以上方法结果接近（±1），取它们的众数
        from collections import Counter
        close_groups = []
        for v in values:
            close_groups.extend([v - 1, v, v + 1])
        counter = Counter(close_groups)
        best_val, best_count = counter.most_common(1)[0]
        if best_count >= 2:
            # 取最接近这个值的实际检测值
            closest = min(values, key=lambda x: abs(x - best_val))
            return closest, has_ruling

        # morph 和 proj 双峰检查（proj = morph * 2）
        if result_a is not None and result_b is not None:
            if result_a >= 4 and result_b > 0 and abs(result_a * 2 - result_b) <= 1:
                return result_a, has_ruling

        # 取中位数
        return int(np.median(values)), has_ruling

    def _morph_line_count(self, bw: np.ndarray, rh: int, w: int) -> int | None:
        """形态学方法：提取界行 → 用峰数推算行数。

        尝试多个 kernel 大小，取检测到最多峰的结果（更充分的检测）。
        """
        best_peaks = []
        for div, min_v_ratio in [(4, 0.1), (5, 0.1), (7, 0.06)]:
            v_kernel_len = max(rh // div, 15)
            v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_kernel_len))
            v_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, v_kernel)
            v_proj = np.sum(v_lines, axis=0) / 255

            min_v = rh * min_v_ratio
            min_dist = max(w // 30, 3)
            peaks = self._find_peaks(v_proj, min_v, min_dist)

            if len(peaks) > len(best_peaks):
                best_peaks = peaks

        if len(best_peaks) >= 3:
            return self._spacing_based_count(best_peaks, w)
        return None

    def _cc_line_count(self, bw: np.ndarray, rh: int, w: int) -> int | None:
        """连通分量聚类法：通过字符中心 x 坐标聚类推算列数。

        适用于低分辨率图片，作为投影法的补充。
        """
        margin_x = int(w * 0.08)
        margin_y = int(rh * 0.05)
        roi = bw[margin_y:rh - margin_y, margin_x:w - margin_x]
        rh2, rw2 = roi.shape

        if rh2 < 30 or rw2 < 30:
            return None

        n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(roi, connectivity=8)

        min_area = rh2 * rw2 * 0.0003
        max_area = rh2 * rw2 * 0.015

        cx_list = []
        for j in range(1, n_labels):
            area = stats[j, cv2.CC_STAT_AREA]
            bw_w = stats[j, cv2.CC_STAT_WIDTH]
            bw_h = stats[j, cv2.CC_STAT_HEIGHT]
            if area < min_area or area > max_area:
                continue
            if max(bw_w, bw_h) / max(min(bw_w, bw_h), 1) > 5:
                continue
            cx_list.append(centroids[j][0])

        if len(cx_list) < 10:
            return None

        # 直方图聚类
        bin_width = max(rw2 // 30, 8)
        n_bins = rw2 // bin_width
        if n_bins < 3:
            return None

        hist, _ = np.histogram(cx_list, bins=n_bins, range=(0, rw2))
        threshold = np.max(hist) * 0.3

        # 计算列数（连续高值 bin 为一列）
        in_cluster = False
        clusters = 0
        for v in hist:
            if v > threshold:
                if not in_cluster:
                    clusters += 1
                    in_cluster = True
            else:
                in_cluster = False

        if 3 <= clusters <= 15:
            return clusters
        return None

    def _proj_line_count(self, bw: np.ndarray, rh: int, w: int) -> int | None:
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
        """基于峰值间距和数量推算行数。

        两种估算取较大值（避免因漏检峰而低估）：
        1. 过滤后的 peaks 数 - 1
        2. content_width / median_spacing（覆盖漏检的峰）
        """
        if len(peaks) < 2:
            return None

        spacings = [peaks[i + 1] - peaks[i] for i in range(len(peaks) - 1)]
        if not spacings:
            return None

        median_spacing = np.median(spacings)
        if median_spacing < 5:
            return None

        # 过滤首尾异常间距（版心或边框导致的额外峰）
        filtered_peaks = list(peaks)
        if len(spacings) >= 3:
            if spacings[0] > median_spacing * 1.8:
                filtered_peaks = filtered_peaks[1:]
            spacings2 = [filtered_peaks[i + 1] - filtered_peaks[i] for i in range(len(filtered_peaks) - 1)]
            if spacings2 and spacings2[-1] > median_spacing * 1.8:
                filtered_peaks = filtered_peaks[:-1]

        if len(filtered_peaks) < 2:
            return None

        # 方法1：峰数 - 1
        count_by_peaks = len(filtered_peaks) - 1

        # 方法2：间距法
        content_width = filtered_peaks[-1] - filtered_peaks[0]
        count_by_spacing = round(content_width / median_spacing)

        # 取较大值（避免因边缘峰漏检而低估）
        estimated = max(count_by_peaks, count_by_spacing)

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
