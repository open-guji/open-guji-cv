"""页面布局分析器：检测已剪切/未剪切、行数等。"""

import cv2
import numpy as np

from .base import BaseAnalyzer


class PageLayoutAnalyzer(BaseAnalyzer):
    """检测古籍页面的布局类型。

    判断依据：
    1. 宽高比：未剪切筒子页通常宽 > 高（横向），已剪切半页通常高 > 宽（纵向）
    2. 中线对称性：未剪切页在中央有对称结构（版心）
    """

    name = "page_layout"

    # 宽高比阈值
    UNCUT_ASPECT_RATIO_MIN = 1.1   # 宽/高 > 1.1 倾向于未剪切
    CUT_ASPECT_RATIO_MAX = 0.9     # 宽/高 < 0.9 倾向于已剪切

    def analyze(self, images: list[np.ndarray]) -> dict:
        aspect_ratios = []
        symmetry_scores = []

        for img in images:
            h, w = img.shape[:2]
            ar = w / h
            aspect_ratios.append(ar)

            # 中线对称性检测
            sym_score = self._check_center_symmetry(img)
            symmetry_scores.append(sym_score)

        avg_ar = np.mean(aspect_ratios)
        avg_sym = np.mean(symmetry_scores)

        # 综合判断
        if avg_ar > self.UNCUT_ASPECT_RATIO_MIN:
            page_type = "uncut_full"
            confidence = min(1.0, (avg_ar - self.UNCUT_ASPECT_RATIO_MIN) * 5 + 0.6)
        elif avg_ar < self.CUT_ASPECT_RATIO_MAX:
            page_type = "cut_half"
            confidence = min(1.0, (self.CUT_ASPECT_RATIO_MAX - avg_ar) * 5 + 0.6)
        else:
            # 模糊地带，用对称性辅助判断
            page_type = "uncut_full" if avg_sym > 0.7 else "cut_half"
            confidence = 0.5 + avg_sym * 0.3

        # 估算行数
        lines_per_page = self._estimate_lines_per_page(images, page_type)

        return {
            "page_type": page_type,
            "lines_per_page": lines_per_page,
            "_confidence": {
                "page_type": confidence,
                "lines_per_page": 0.5,  # 行数估计置信度较低，后续由边框检测修正
            },
        }

    def _check_center_symmetry(self, img: np.ndarray) -> float:
        """检测图像中线对称性（未剪切筒子页在中央有对称的版心结构）。

        Returns:
            对称性得分 0~1，越高越对称。
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape

        # 取中央纵向条带（宽度为图像宽度的 10%）
        strip_w = max(w // 20, 5)
        center_x = w // 2
        left_strip = gray[:, center_x - strip_w: center_x].astype(np.float32)
        right_strip = gray[:, center_x: center_x + strip_w].astype(np.float32)

        # 翻转右侧条带进行比较
        right_flipped = np.flip(right_strip, axis=1)

        # 计算归一化互相关
        diff = np.abs(left_strip - right_flipped)
        similarity = 1.0 - np.mean(diff) / 255.0

        return float(similarity)

    def _estimate_lines_per_page(self, images: list[np.ndarray],
                                  page_type: str) -> int:
        """粗略估计每半页的行数。

        通过对二值化图像做垂直投影来估算。
        这是一个粗略估计，后续由边框检测精确确定。
        """
        # 常见的行数：8 或 9
        # 这里做简单的默认处理，后续 Phase 3 会精确检测
        # 未剪切筒子页通常每半页 9 行，已剪切通常 8 行
        if page_type == "uncut_full":
            return 9
        return 8
