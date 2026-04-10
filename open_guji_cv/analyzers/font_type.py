"""字体类型分析器：检测印刷/手写。"""

import cv2
import numpy as np

from .base import BaseAnalyzer


class FontTypeAnalyzer(BaseAnalyzer):
    """检测古籍文字是印刷（刻本）还是手写（抄本）。

    印刷/刻本特征：笔画宽度均匀、字符大小一致、边缘锐利
    手写/抄本特征：笔画宽度变化大、字符大小不一、边缘柔和

    算法：
    1. 提取内容区域的连通分量（字符）
    2. 分析字符边界框面积的变异系数 — 印刷体更均匀
    3. 分析笔画宽度的变异系数（距离变换）— 印刷体更均匀
    """

    name = "font_type"

    # 变异系数阈值：低于此值为印刷体
    SIZE_CV_THRESHOLD = 0.65
    STROKE_CV_THRESHOLD = 0.70

    def analyze(self, images: list[np.ndarray]) -> dict:
        size_cvs = []
        stroke_cvs = []

        for img in images:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
            size_cv, stroke_cv = self._analyze_character_regularity(gray)
            if size_cv is not None:
                size_cvs.append(size_cv)
            if stroke_cv is not None:
                stroke_cvs.append(stroke_cv)

        # 综合判断
        printed_score = 0
        total_checks = 0

        if size_cvs:
            avg_size_cv = np.mean(size_cvs)
            total_checks += 1
            if avg_size_cv < self.SIZE_CV_THRESHOLD:
                printed_score += 1

        if stroke_cvs:
            avg_stroke_cv = np.mean(stroke_cvs)
            total_checks += 1
            if avg_stroke_cv < self.STROKE_CV_THRESHOLD:
                printed_score += 1

        if total_checks == 0:
            font_type = "printed"
            confidence = 0.3
        else:
            is_printed = printed_score > total_checks / 2
            font_type = "printed" if is_printed else "handwritten"
            confidence = printed_score / total_checks if is_printed else (total_checks - printed_score) / total_checks

        return {
            "font_type": font_type,
            "_confidence": {"font_type": round(min(1.0, confidence + 0.3), 2)},
        }

    def _analyze_character_regularity(self, gray: np.ndarray) -> tuple[float | None, float | None]:
        """分析字符大小和笔画宽度的规律性。

        Returns:
            (size_cv, stroke_cv) — 变异系数 (std/mean)，越小越规律
        """
        h, w = gray.shape

        # 内容区域
        margin_x = int(w * 0.15)
        margin_y = int(h * 0.12)
        roi = gray[margin_y:h - margin_y, margin_x:w - margin_x]
        rh, rw = roi.shape

        if rh < 50 or rw < 50:
            return None, None

        _, bw = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # 连通分量分析
        n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)

        if n_labels < 10:
            return None, None

        # 过滤：取合理大小的分量（字符级别）
        min_area = (rh * rw) * 0.0005  # 最小面积
        max_area = (rh * rw) * 0.02    # 最大面积
        min_side = max(rh, rw) * 0.01  # 最小边长

        areas = []
        stroke_widths = []

        for i in range(1, n_labels):  # 跳过背景
            area = stats[i, cv2.CC_STAT_AREA]
            bw_w = stats[i, cv2.CC_STAT_WIDTH]
            bw_h = stats[i, cv2.CC_STAT_HEIGHT]

            if area < min_area or area > max_area:
                continue
            if bw_w < min_side or bw_h < min_side:
                continue
            # 排除极端纵横比（可能是栏线等）
            ar = max(bw_w, bw_h) / max(min(bw_w, bw_h), 1)
            if ar > 5:
                continue

            areas.append(area)

            # 笔画宽度：用距离变换在该分量区域采样
            x0 = stats[i, cv2.CC_STAT_LEFT]
            y0 = stats[i, cv2.CC_STAT_TOP]
            comp_mask = (labels[y0:y0 + bw_h, x0:x0 + bw_w] == i).astype(np.uint8)

            if np.count_nonzero(comp_mask) < 5:
                continue

            dist = cv2.distanceTransform(comp_mask, cv2.DIST_L2, 3)
            # 取骨架上的距离值（即笔画半宽）
            skeleton_vals = dist[comp_mask > 0]
            if len(skeleton_vals) > 5:
                mean_sw = np.mean(skeleton_vals)
                if mean_sw > 0.5:
                    stroke_widths.append(mean_sw)

        # 计算变异系数
        size_cv = None
        if len(areas) >= 10:
            mean_a = np.mean(areas)
            if mean_a > 0:
                size_cv = float(np.std(areas) / mean_a)

        stroke_cv = None
        if len(stroke_widths) >= 10:
            mean_sw = np.mean(stroke_widths)
            if mean_sw > 0:
                stroke_cv = float(np.std(stroke_widths) / mean_sw)

        return size_cv, stroke_cv
