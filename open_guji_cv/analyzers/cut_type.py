"""切分类型分析器：检测图片是否需要切分，以及切分方向。"""

import cv2
import numpy as np

from .base import BaseAnalyzer


class CutTypeAnalyzer(BaseAnalyzer):
    """检测古籍图片的切分类型。

    cut_type:
    - "none": 不需要切分（cut_half 半页、uncut_full 筒子页、单栏现代印刷等）
    - "vertical_cut": 需要垂直切分（spread 对开页，两个独立页框左右排列）
    - "horizontal_cut": 需要水平切分（上下两栏排列，常见于影印本）

    算法：
    1. vertical_cut: 中央纵向间隙检测（spread 特征：两帧之间墨迹接近零）
    2. horizontal_cut: 中部横向间隙检测（上下两栏之间有明显的水平空白带）
    3. none: 以上都不满足
    """

    name = "cut_type"

    # 中缝间隙检测（垂直切分）
    CENTER_GAP_INK_THRESHOLD = 0.01

    # 水平间隙检测（水平切分）
    HGAP_MIN_WIDTH_RATIO = 0.5    # 间隙宽度至少占页宽的 50%
    HGAP_MAX_INK_RATIO = 0.02     # 间隙区域墨迹密度 < 2%
    HGAP_MIN_HEIGHT_RATIO = 0.02  # 间隙最小高度占图片高度的比例

    def analyze(self, images: list[np.ndarray]) -> dict:
        v_scores = []
        h_scores = []

        for img in images:
            v_scores.append(self._detect_vertical_gap(img))
            h_scores.append(self._detect_horizontal_gap(img))

        avg_v = np.mean(v_scores) if v_scores else 0
        avg_h = np.mean(h_scores) if h_scores else 0

        # 垂直切分优先（更常见）
        if avg_v > 0.5:
            cut_type = "vertical_cut"
            confidence = avg_v
        elif avg_h > 0.5:
            cut_type = "horizontal_cut"
            confidence = avg_h
        else:
            cut_type = "none"
            confidence = 1.0 - max(avg_v, avg_h)

        return {
            "cut_type": cut_type,
            "_confidence": {"cut_type": round(min(1.0, confidence), 2)},
        }

    def _detect_vertical_gap(self, img: np.ndarray) -> float:
        """检测图片中央是否存在纵向间隙（spread 的两帧之间）。

        在中央 40%-60% 宽度范围内，逐列计算墨迹密度。
        如果存在某列的墨迹密度极低，说明有纵向间隙。
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape

        # 宽高比 < 0.95 的不可能是 spread
        if w / h < 0.95:
            return 0.0

        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        y0, y1 = int(h * 0.1), int(h * 0.9)
        c0, c1 = int(w * 0.40), int(w * 0.60)
        center_cols = bw[y0:y1, c0:c1]

        col_ink = np.mean(center_cols, axis=0) / 255.0
        min_ink = float(np.min(col_ink))

        if min_ink < self.CENTER_GAP_INK_THRESHOLD:
            return min(1.0, (self.CENTER_GAP_INK_THRESHOLD - min_ink) * 50 + 0.7)
        return 0.0

    def _detect_horizontal_gap(self, img: np.ndarray) -> float:
        """检测图片中部是否存在水平间隙（上下两栏之间的空白带）。

        在中央 30%-70% 高度范围内，逐行计算墨迹密度。
        如果存在连续的低密度行带，说明有水平间隙。
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape

        # 宽高比 > 1.2 的不太可能是上下两栏
        if w / h > 1.2:
            return 0.0

        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # 在中央横向区域检测（排除左右边距）
        x0, x1 = int(w * 0.1), int(w * 0.9)
        y0, y1 = int(h * 0.30), int(h * 0.70)
        roi = bw[y0:y1, x0:x1]
        rh, rw = roi.shape

        # 逐行墨迹密度
        row_ink = np.mean(roi, axis=1) / 255.0

        # 找连续的低墨迹行（间隙）
        gap_mask = row_ink < self.HGAP_MAX_INK_RATIO

        # 找最长连续间隙
        best_len = 0
        cur_len = 0
        for is_gap in gap_mask:
            if is_gap:
                cur_len += 1
                best_len = max(best_len, cur_len)
            else:
                cur_len = 0

        min_height = max(int(h * self.HGAP_MIN_HEIGHT_RATIO), 30)
        if best_len >= min_height:
            # 间隙够宽，确认是水平切分
            return min(1.0, best_len / 30.0)
        return 0.0
