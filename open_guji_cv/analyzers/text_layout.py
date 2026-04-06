"""文字布局分析器：检测每行字数、夹注等。"""

import cv2
import numpy as np

from .base import BaseAnalyzer


class TextLayoutAnalyzer(BaseAnalyzer):
    """检测古籍文字布局特征。

    检测项：
    - chars_per_line: 每行（列）的字数，None 表示不固定
    - has_marginal_notes: 是否有夹注（一列内双列小字）
    """

    name = "text_layout"

    # 夹注检测参数
    DUAL_PEAK_MIN_RATIO = 0.25  # 双峰之间谷值 < 峰值 * ratio → 有分裂
    MARGINAL_NOTE_MIN_COLS = 2  # 至少 2 列出现双峰才判定有夹注

    def analyze(self, images: list[np.ndarray]) -> dict:
        chars_counts = []
        marginal_votes = []

        for img in images:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img

            n_chars = self._estimate_chars_per_line(gray)
            if n_chars is not None:
                chars_counts.append(n_chars)

            has_mn = self._detect_marginal_notes(gray)
            marginal_votes.append(has_mn)

        # 每行字数
        if chars_counts:
            from collections import Counter
            counter = Counter(chars_counts)
            most_common_val, most_common_count = counter.most_common(1)[0]
            # 如果众数覆盖率低于 50%，认为字数不固定
            if most_common_count / len(chars_counts) < 0.5:
                chars_per_line = None
                chars_confidence = 0.3
            else:
                chars_per_line = most_common_val
                chars_confidence = most_common_count / len(chars_counts)
        else:
            chars_per_line = None
            chars_confidence = 0.2

        # 夹注
        mn_ratio = sum(marginal_votes) / len(marginal_votes) if marginal_votes else 0
        has_marginal_notes = mn_ratio > 0.3  # 30% 以上的页面检测到夹注

        return {
            "chars_per_line": chars_per_line,
            "has_marginal_notes": has_marginal_notes,
            "_confidence": {
                "chars_per_line": round(chars_confidence, 2),
                "has_marginal_notes": round(mn_ratio, 2) if has_marginal_notes else round(1.0 - mn_ratio, 2),
            },
        }

    # ────────────────── 每行字数检测 ──────────────────

    def _estimate_chars_per_line(self, gray: np.ndarray) -> int | None:
        """估算每行（竖列）的字数。

        方法：在内容区域选取几列，对每列做垂直投影（沿高度方向），
        计算文字行数（暗带数量）。

        Returns:
            估计的每行字数，或 None
        """
        h, w = gray.shape

        # 二值化
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # 先找内容区域的大致范围（避开边框）
        margin_x = int(w * 0.15)
        margin_y = int(h * 0.1)
        content = bw[margin_y:h - margin_y, margin_x:w - margin_x]
        ch, cw = content.shape

        if ch < 50 or cw < 50:
            return None

        # 取中间几列的平均垂直投影
        n_samples = min(5, cw // 20)
        if n_samples < 1:
            return None

        sample_xs = np.linspace(cw * 0.2, cw * 0.8, n_samples).astype(int)
        col_width = max(cw // 30, 5)  # 每列采样宽度

        char_counts = []
        for x in sample_xs:
            x0 = max(0, x - col_width // 2)
            x1 = min(cw, x + col_width // 2)
            col_strip = content[:, x0:x1]

            # 垂直投影：沿高度方向的墨迹密度
            v_proj = np.mean(col_strip, axis=1)

            # 平滑
            kernel_size = max(ch // 80, 3)
            if kernel_size % 2 == 0:
                kernel_size += 1
            v_smooth = cv2.GaussianBlur(
                v_proj.reshape(-1, 1), (kernel_size, 1), 0).flatten()

            # 计算字数：峰值数量
            min_height = np.max(v_smooth) * 0.15
            min_dist = ch // 35  # 字间距至少为图高的 1/35
            n_chars = self._count_peaks(v_smooth, min_height, min_dist)

            if 10 <= n_chars <= 35:
                char_counts.append(n_chars)

        if not char_counts:
            return None

        # 取中值
        return int(np.median(char_counts))

    # ────────────────── 夹注检测 ──────────────────

    def _detect_marginal_notes(self, gray: np.ndarray) -> bool:
        """检测是否存在夹注（双列小字）。

        方法：对每个文字列做水平投影，如果某列的水平投影出现
        双峰（两个并排的文字区域），说明该列有夹注。

        Returns:
            该页是否检测到夹注
        """
        h, w = gray.shape
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # 内容区域
        margin_x = int(w * 0.12)
        margin_y = int(h * 0.15)
        content = bw[margin_y:h - margin_y, margin_x:w - margin_x]
        ch, cw = content.shape

        if ch < 50 or cw < 50:
            return False

        # 先通过垂直投影找到各列的位置
        col_proj = np.sum(content, axis=0).astype(np.float64) / 255
        kernel = max(cw // 60, 3)
        if kernel % 2 == 0:
            kernel += 1
        col_smooth = cv2.GaussianBlur(col_proj.reshape(1, -1), (kernel, 1), 0).flatten()

        # 找列位置
        min_height = ch * 0.1
        min_dist = cw // 20
        col_positions = self._find_peak_positions(col_smooth, min_height, min_dist)

        if len(col_positions) < 3:
            return False

        # 对每列做水平投影，检查双峰
        dual_peak_count = 0
        col_half_width = min_dist // 2

        for cx in col_positions:
            x0 = max(0, cx - col_half_width)
            x1 = min(cw, cx + col_half_width)
            col_strip = content[:, x0:x1]

            if col_strip.shape[1] < 5:
                continue

            # 水平投影
            h_proj = np.sum(col_strip, axis=0).astype(np.float64) / 255

            # 检查是否有双峰
            if self._has_dual_peak(h_proj):
                dual_peak_count += 1

        return dual_peak_count >= self.MARGINAL_NOTE_MIN_COLS

    def _has_dual_peak(self, profile: np.ndarray) -> bool:
        """检查水平投影是否呈现双峰特征（两个并排的文字区域）。"""
        n = len(profile)
        if n < 8:
            return False

        # 平滑
        kernel = max(n // 10, 3)
        if kernel % 2 == 0:
            kernel += 1
        smooth = cv2.GaussianBlur(profile.reshape(1, -1), (kernel, 1), 0).flatten()

        max_val = np.max(smooth)
        if max_val < 5:
            return False

        # 找峰值
        peaks = self._find_peak_positions(smooth, max_val * 0.3, n // 6)

        if len(peaks) != 2:
            return False

        # 检查两峰之间的谷值
        valley_region = smooth[peaks[0]:peaks[1]]
        if len(valley_region) < 2:
            return False

        valley_min = np.min(valley_region)
        peak_avg = (smooth[peaks[0]] + smooth[peaks[1]]) / 2

        # 谷值明显低于峰值
        return valley_min < peak_avg * self.DUAL_PEAK_MIN_RATIO

    # ────────────────── 工具方法 ──────────────────

    @staticmethod
    def _count_peaks(signal: np.ndarray, min_height: float,
                     min_distance: int) -> int:
        """计算峰值数量。"""
        peaks = TextLayoutAnalyzer._find_peak_positions(signal, min_height, min_distance)
        return len(peaks)

    @staticmethod
    def _find_peak_positions(signal: np.ndarray, min_height: float,
                             min_distance: int) -> list[int]:
        """找到所有峰值的位置。"""
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

        # 合并太近的峰值
        if not peaks:
            return []

        merged = [peaks[0]]
        for p in peaks[1:]:
            if p - merged[-1] >= min_distance:
                merged.append(p)

        return merged
