"""字符网格检测器 —— 在列结构基础上定位每个字符的网格位置。

核心算法：
1. 水平投影法分割字符区域（适合竖排文字）
2. PaddleOCR 做整列文字识别获取文字内容
3. 用先验知识（chars_per_line）约束和修正分割结果
4. 将 OCR 识别的文字逐个对应到投影分割的槽位

三种格子类型：
- "char": 有文字的字符格子，之间可有缝隙，不重叠
- "empty": 空白字符格子，连续等高无缝隙，占字符数
- "margin": 边距格子，列首/列尾微小间距，不占字符数
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np

from .ocr_detector import OcrDetector, WordBox

if TYPE_CHECKING:
    from ..profile import BookProfile


class CharGridDetector:
    """在列结构基础上，检测每个字符的网格位置。"""

    # 投影分割参数
    PROJ_THRESHOLD = 2           # 至少 N 个黑色像素才算文字行
    MIN_CHAR_HEIGHT = 10         # 低于此高度的区域视为噪点
    SPLIT_RATIO = 1.4            # 区域高度 > 理论字高 * 此比率时二次分割

    # 字高约束
    CHAR_HEIGHT_MIN_RATIO = 0.7
    CHAR_HEIGHT_MAX_RATIO = 1.3

    # 列宽过滤
    MIN_COL_WIDTH = 30             # 列像素宽度低于此值时视为无效列

    # 夹注检测参数
    MIN_JIAZHU_ROWS = 2            # 最少连续双峰区域数才认定为夹注段
    JIAZHU_GAP_THRESHOLD = 0.5     # 谷底均值 < min(左,右)均值 × 此比率视为有间隙
    JIAZHU_WINDOW_SIZE = 5         # 滑动窗口大小（区域数）

    def __init__(self, ocr_detector: OcrDetector | None = None):
        self.ocr = ocr_detector or OcrDetector()

    def detect(self, image: np.ndarray, layout: dict,
               profile: BookProfile) -> dict:
        """对整张图做字符网格检测。"""
        h, w = image.shape[:2]
        expected_chars = profile.chars_per_line or 21

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

        borders = layout.get("borders", {})
        inner_frame = borders.get("inner_frame", {})
        col_top = inner_frame.get("top", {}).get("intercept", 0)
        col_bottom = inner_frame.get("bottom", {}).get("intercept", h)

        columns_info = layout.get("columns", {}).get("columns", [])
        if not columns_info:
            columns_info = borders.get("columns", [])

        col_height = col_bottom - col_top
        theoretical_char_h = col_height / expected_chars

        result_columns = []
        all_char_heights = []

        for col in columns_info:
            col_idx = col["index"]
            left_x = col["left_x"]
            right_x = col["right_x"]

            pad = 4
            x1 = max(0, int(left_x) + pad)
            x2 = min(w, int(right_x) - pad)
            y1 = max(0, int(col_top))
            y2 = min(h, int(col_bottom))

            if x2 <= x1 or y2 <= y1 or (x2 - x1) < self.MIN_COL_WIDTH:
                print(f"  [WARN] col {col_idx}: img_w={w}, x1={x1}, x2={x2}, "
                      f"left_x={left_x:.0f}, right_x={right_x:.0f} -> empty_column")
                result_columns.append(self._empty_column(
                    col_idx, left_x, right_x, col_top, col_bottom, expected_chars))
                continue

            col_gray = gray[y1:y2, x1:x2]

            # Step 1: 投影法分割字符区域
            regions = self._projection_segment(col_gray, theoretical_char_h)

            # Step 1.5: 夹注区域检测（在局部坐标下进行）
            col_width = x2 - x1
            jiazhu_ranges = self._detect_jiazhu_regions(
                col_gray, regions, col_width, theoretical_char_h)

            col_image = image[y1:y2, x1:x2]

            if jiazhu_ranges:
                # ── 含夹注的列：按段处理 ──
                cells, ocr_text, jiazhu_info = self._build_jiazhu_column(
                    col_gray, col_image, regions, jiazhu_ranges,
                    col_top, col_bottom, expected_chars,
                    theoretical_char_h, y1, col_width)

                col_result = {
                    "index": col_idx,
                    "left_x": left_x,
                    "right_x": right_x,
                    "ocr_text": ocr_text,
                    "cells": cells,
                    "has_jiazhu": True,
                    "jiazhu_ranges": jiazhu_info,
                }
            else:
                # ── 普通列 ──
                # 局部坐标 → 全图坐标
                regions = [(int(y1 + r_top), int(y1 + r_bot))
                           for r_top, r_bot in regions]

                # OCR 识别整列文字
                ocr_text, word_boxes = self._ocr_column_words(col_image, y1)

                # 构建字符网格
                cells, char_h = self._build_char_grid(
                    regions, ocr_text, word_boxes,
                    col_top, col_bottom, expected_chars,
                    theoretical_char_h)

                if char_h > 0:
                    all_char_heights.append(char_h)

                col_result = {
                    "index": col_idx,
                    "left_x": left_x,
                    "right_x": right_x,
                        "ocr_text": ocr_text,
                        "cells": cells,
                    }

            result_columns.append(col_result)

        avg_char_h = float(np.mean(all_char_heights)) if all_char_heights else 0.0

        return {
            "image_size": {"width": w, "height": h},
            "chars_per_line": expected_chars,
            "char_height_estimated": round(avg_char_h, 2),
            "columns": result_columns,
        }

    # ─── 投影法分割 ─────────────────────────────────────────

    def _projection_segment(
        self,
        col_gray: np.ndarray,
        theoretical_char_h: float,
    ) -> list[tuple[int, int]]:
        """水平投影法分割竖排文字的字符区域。

        Returns:
            [(y_start, y_end), ...] 每个字符区域的局部坐标
        """
        h, w = col_gray.shape

        _, binary = cv2.threshold(col_gray, 128, 255, cv2.THRESH_BINARY)
        h_proj = w - np.sum(binary, axis=1) / 255.0

        is_text = h_proj > self.PROJ_THRESHOLD
        raw_regions = self._find_continuous_regions(is_text, h)

        regions = [(s, e) for s, e in raw_regions if (e - s) >= self.MIN_CHAR_HEIGHT]

        refined = []
        for start, end in regions:
            region_h = end - start
            if region_h > theoretical_char_h * self.SPLIT_RATIO:
                sub_regions = self._split_large_region(
                    h_proj[start:end], start, theoretical_char_h)
                refined.extend(sub_regions)
            else:
                refined.append((start, end))

        return refined

    # ─── 夹注检测 ─────────────────────────────────────────

    def _detect_jiazhu_regions(
        self,
        col_gray: np.ndarray,
        regions: list[tuple[int, int]],
        col_width: int,
        theoretical_char_h: float,
    ) -> list[tuple[int, int]]:
        """检测列中的所有夹注区域（支持多段交替）。

        两阶段检测：
        1. 全列垂直投影：若整列呈双峰分布，标记所有区域为夹注
        2. 滑动窗口：对连续 N 个区域覆盖的 y 范围做垂直投影双峰检测

        核心原理：夹注的两个子列字符交错排列，单个投影区域只包含
        一侧字符的墨迹。必须合并多个区域（或整列）的垂直投影，
        才能看到左右两侧的双峰分布。

        Args:
            col_gray: 列的灰度图像（局部坐标系）
            regions: 投影分割结果，局部坐标 [(y_start, y_end), ...]
            col_width: 列的像素宽度
            theoretical_char_h: 正文的理论字高（像素）

        Returns:
            list of (start_region_idx, end_region_idx)，inclusive
            空列表表示此列无夹注
        """
        if len(regions) < self.MIN_JIAZHU_ROWS:
            return []

        # 额外内缩以排除列边缘的界行线
        border_pad = max(4, int(col_width * 0.05))
        x_start = border_pad
        x_end = col_width - border_pad
        eff_w = x_end - x_start
        if eff_w < 20:
            return []

        # ── 阶段 1: 全列垂直投影检测 ──
        col_h = col_gray.shape[0]
        col_trimmed = col_gray[:, x_start:x_end]
        full_vproj = np.sum(col_trimmed < 128, axis=0).astype(float)
        if self._check_dual_peak(full_vproj, eff_w, col_h):
            return [(0, len(regions) - 1)]

        # ── 阶段 2: 滑动窗口检测 ──
        is_jiazhu = [False] * len(regions)
        ws = min(self.JIAZHU_WINDOW_SIZE, len(regions))

        for win_start in range(len(regions) - ws + 1):
            if all(is_jiazhu[win_start:win_start + ws]):
                continue

            y_top = regions[win_start][0]
            y_bot = regions[win_start + ws - 1][1]
            window_img = col_gray[y_top:y_bot, x_start:x_end]
            v_proj = np.sum(window_img < 128, axis=0).astype(float)
            win_h = y_bot - y_top

            if self._check_dual_peak(v_proj, eff_w, win_h):
                for k in range(win_start, win_start + ws):
                    is_jiazhu[k] = True

        # 连续 True 段合并，>= MIN_JIAZHU_ROWS 才认定
        jiazhu_ranges: list[tuple[int, int]] = []
        i = 0
        while i < len(is_jiazhu):
            if is_jiazhu[i]:
                start = i
                while i < len(is_jiazhu) and is_jiazhu[i]:
                    i += 1
                if (i - start) >= self.MIN_JIAZHU_ROWS:
                    jiazhu_ranges.append((start, i - 1))  # inclusive
            else:
                i += 1

        return jiazhu_ranges

    def _check_dual_peak(
        self,
        v_proj: np.ndarray,
        eff_w: int,
        img_height: int,
    ) -> bool:
        """检查垂直投影是否呈双峰分布（夹注特征）。

        预处理：抑制列边缘的界行线及其衰减尾部，防止假阳性。
        动态谷底搜索：迭代寻找最深谷底，检查两侧是否各有显著墨迹峰。
        """
        global_mean = float(np.mean(v_proj))
        if global_mean < 1.0:
            return False

        # ── 预处理：抑制边缘界行线 ──
        # 用中间区域的中位数估算背景水平，高于 3 倍背景的边缘像素归零
        v_clean = v_proj.copy()
        mid_s = eff_w // 4
        mid_e = eff_w * 3 // 4
        if mid_e > mid_s:
            background = float(np.median(v_clean[mid_s:mid_e]))
        else:
            background = global_mean
        tail_thresh = max(background * 3, min(img_height * 0.15, eff_w * 1.0))

        # 从左边缘向内扫描并抑制
        i = 0
        while i < eff_w // 4 and v_clean[i] > tail_thresh:
            v_clean[i] = 0
            i += 1
        # 从右边缘向内扫描并抑制
        i = eff_w - 1
        while i > eff_w * 3 // 4 and v_clean[i] > tail_thresh:
            v_clean[i] = 0
            i -= 1

        # 抑制后重新计算均值
        global_mean = float(np.mean(v_clean))
        if global_mean < 1.0:
            return False

        valley_half = max(2, eff_w // 40)
        min_ink = max(2, global_mean * 0.1)
        min_active = max(5, int(eff_w * 0.15))

        # ── 迭代式谷底搜索 ──
        working = v_clean.copy()
        mask_radius = max(5, eff_w // 10)
        
        # 搜索范围为中间 40%，容纳版面偏差和不等宽夹注
        mid = eff_w // 2
        search_radius = max(10, eff_w // 5)
        search_start = max(0, mid - search_radius)
        search_end = min(eff_w, mid + search_radius)

        for _ in range(3):
            search_zone = working[search_start:search_end]
            if len(search_zone) == 0 or np.max(search_zone) < 1.0:
                break

            valley_x = search_start + int(np.argmin(search_zone))

            v_start = max(0, valley_x - valley_half)
            v_end = min(eff_w, valley_x + valley_half + 1)
            valley_mean = float(np.mean(v_clean[v_start:v_end]))

            left_zone = v_clean[:v_start]
            right_zone = v_clean[v_end:]

            if len(left_zone) < 3 or len(right_zone) < 3:
                m_start = max(0, valley_x - mask_radius)
                m_end = min(eff_w, valley_x + mask_radius)
                working[m_start:m_end] = np.max(working)
                continue

            left_mean = float(np.mean(left_zone))
            right_mean = float(np.mean(right_zone))
            side_max = max(left_mean, right_mean)

            if side_max < 1.0:
                break

            # 两侧都需有显著墨迹（排除单侧文字 / 空白区边缘）
            # 允许两侧密度差 2.9 倍，适应夹注中书名/注释字数不对称
            if (left_mean >= side_max * 0.35
                    and right_mean >= side_max * 0.35):
                side_min = min(left_mean, right_mean)
                # JIAZHU_GAP_THRESHOLD 为类属性，缺省改低（更严）
                gap_thresh = min(0.3, self.JIAZHU_GAP_THRESHOLD) 
                if valley_mean < side_min * gap_thresh:
                    # 峰宽度检查：两边应该都有足够宽度的墨迹
                    left_active = int(np.sum(left_zone > min_ink))
                    right_active = int(np.sum(right_zone > min_ink))
                    # 谷底位置检查：必须在有效宽度的 30%-70% 之间
                    valley_ratio = valley_x / eff_w if eff_w > 0 else 0.5
                    if (left_active >= min_active
                            and right_active >= min_active
                            and 0.30 <= valley_ratio <= 0.70):
                        return True

            # 当前谷底不满足条件，遮蔽后重试下一个
            m_start = max(0, valley_x - mask_radius)
            m_end = min(eff_w, valley_x + mask_radius)
            working[m_start:m_end] = np.max(working)

        return False

    def _split_jiazhu_subcols(
        self,
        col_gray: np.ndarray,
        jiazhu_y_top: int,
        jiazhu_y_bottom: int,
        col_width: int,
    ) -> tuple[np.ndarray, np.ndarray, int]:
        """将夹注区域图像拆分为左右两个子列。

        在夹注区域的中间 30% 范围内找垂直投影最小值作为分割线。

        Args:
            col_gray: 列灰度图像（局部坐标）
            jiazhu_y_top: 夹注区域顶部 y（局部坐标）
            jiazhu_y_bottom: 夹注区域底部 y（局部坐标）
            col_width: 列宽度

        Returns:
            (left_sub, right_sub, split_x):
                left_sub: 左子列图像（sub_col=2，后读）
                right_sub: 右子列图像（sub_col=1，先读）
                split_x: 分割线的 x 坐标（局部）
        """
        jiazhu_img = col_gray[jiazhu_y_top:jiazhu_y_bottom, :]
        v_proj = np.sum(jiazhu_img < 128, axis=0).astype(float)

        # 在列宽中间 30% 范围内找投影最小值
        mid = col_width // 2
        search_start = max(0, int(mid * 0.7))
        search_end = min(col_width, int(mid * 1.3))
        if search_end <= search_start:
            search_start, search_end = mid - 5, mid + 5
        split_x = search_start + int(np.argmin(v_proj[search_start:search_end]))

        # 古籍竖排阅读顺序：右→左
        # 图片中 split_x 右侧（x大）= sub_col 1（先读）
        # 图片中 split_x 左侧（x小）= sub_col 2（后读）
        left_sub = col_gray[jiazhu_y_top:jiazhu_y_bottom, :split_x]
        right_sub = col_gray[jiazhu_y_top:jiazhu_y_bottom, split_x:]

        return left_sub, right_sub, split_x

    @staticmethod
    def _segment_column(
        regions: list[tuple[int, int]],
        jiazhu_ranges: list[tuple[int, int]],
    ) -> list[tuple[str, list[int]]]:
        """将投影区域分为正文段和夹注段的交替序列。

        Args:
            regions: 投影分割区域列表
            jiazhu_ranges: 夹注区域索引范围列表 [(start, end), ...]，inclusive

        Returns:
            [("normal", [idx, ...]), ("jiazhu", [idx, ...]), ...] 交替序列
        """
        segments: list[tuple[str, list[int]]] = []
        prev_end = 0
        for jz_start, jz_end in sorted(jiazhu_ranges):
            if prev_end < jz_start:
                segments.append(("normal", list(range(prev_end, jz_start))))
            segments.append(("jiazhu", list(range(jz_start, jz_end + 1))))
            prev_end = jz_end + 1
        if prev_end < len(regions):
            segments.append(("normal", list(range(prev_end, len(regions)))))
        return segments

    @staticmethod
    def _find_continuous_regions(
        is_text: np.ndarray,
        length: int,
    ) -> list[tuple[int, int]]:
        """从布尔数组中找连续 True 的区域。"""
        changes = np.diff(is_text.astype(np.int8))
        starts = list(np.where(changes == 1)[0] + 1)
        ends = list(np.where(changes == -1)[0] + 1)

        if is_text[0]:
            starts.insert(0, 0)
        if is_text[-1]:
            ends.append(length)

        return list(zip(starts, ends))

    def _split_large_region(
        self,
        proj_slice: np.ndarray,
        offset: int,
        theoretical_char_h: float,
    ) -> list[tuple[int, int]]:
        """将过大的投影区域在内部谷底处分割。

        策略：在区域内寻找投影局部最小值（谷底），按与理论字高的
        间距约束筛选有效谷底作为分割点。比固定等分更准确。
        """
        region_h = len(proj_slice)
        n_chars_est = region_h / theoretical_char_h
        if n_chars_est <= 1.2:
            return [(offset, offset + region_h)]

        # ── 找所有局部最小值（字间谷底） ──
        min_sep = int(theoretical_char_h * 0.5)  # 相邻谷底最小间距
        valleys = []
        half_win = max(3, int(theoretical_char_h * 0.15))
        mean_proj = float(np.mean(proj_slice))
        valley_thresh = mean_proj * 0.35  # 严格阈值，排除字内间隙
        for y in range(half_win, region_h - half_win):
            window = proj_slice[max(0, y - half_win):y + half_win + 1]
            if proj_slice[y] == window.min() and proj_slice[y] < valley_thresh:
                if not valleys or (y - valleys[-1]) >= min_sep:
                    valleys.append(y)

        if not valleys:
            # 回退到等分法
            n_chars = max(2, round(n_chars_est))
            cuts = [0]
            for i in range(1, n_chars):
                cuts.append(int(i * region_h / n_chars))
            cuts.append(region_h)
        else:
            # 用谷底作为分割点
            cuts = [0] + valleys + [region_h]

        # ── 合并过小的子区域 ──
        merged_cuts = [cuts[0]]
        for c in cuts[1:]:
            if c - merged_cuts[-1] >= self.MIN_CHAR_HEIGHT:
                merged_cuts.append(c)
            else:
                # 过小，合并到前一段
                if len(merged_cuts) > 1:
                    merged_cuts[-1] = c
        if merged_cuts[-1] != region_h:
            merged_cuts.append(region_h)
        cuts = merged_cuts

        result = []
        for i in range(len(cuts) - 1):
            s = offset + cuts[i]
            e = offset + cuts[i + 1]
            if e - s >= self.MIN_CHAR_HEIGHT:
                result.append((s, e))

        return result if result else [(offset, offset + region_h)]

    # ─── OCR 文字识别 ──────────────────────────────────────

    def _ocr_column_words(
        self, col_image: np.ndarray, y_offset: float,
    ) -> tuple[str, list[WordBox]]:
        """对单列图像做 OCR 识别，返回文字和每个字的位置。

        使用 return_word_box=True 获取 CTC 步长估算的单字框。
        返回的 WordBox 坐标已转换为全图坐标（加上 y_offset）。

        Returns:
            (ocr_text, word_boxes):
                ocr_text: 拼接的文字字符串
                word_boxes: 每个字的 WordBox（全图坐标），按 center_y 排序
        """
        words = self.ocr.detect_words(col_image)
        if not words:
            # 回退到行级别 OCR
            boxes = self.ocr.detect_chars(col_image)
            if not boxes:
                return "", []
            best = max(boxes, key=lambda b: b.confidence)
            return best.text, []

        # 转换坐标到全图坐标
        global_words = []
        for w in words:
            global_words.append(WordBox(
                text=w.text,
                x_min=w.x_min,
                y_min=w.y_min + y_offset,
                x_max=w.x_max,
                y_max=w.y_max + y_offset,
                center_y=w.center_y + y_offset,
                height=w.height,
            ))

        ocr_text = "".join(w.text for w in global_words)
        return ocr_text, global_words

    # ─── 夹注列构建 ────────────────────────────────────────

    def _build_jiazhu_column(
        self,
        col_gray: np.ndarray,
        col_image: np.ndarray,
        regions: list[tuple[int, int]],
        jiazhu_ranges: list[tuple[int, int]],
        col_top: float,
        col_bottom: float,
        expected_chars: int,
        theoretical_char_h: float,
        y_offset: int,
        col_width: int,
    ) -> tuple[list[dict], str, list[dict]]:
        """处理含夹注的列：多段正文/夹注交替合并。

        对正文段：整段 OCR + 按区域逐字匹配。
        对夹注段：拆分子列 → 各子列投影分割 + OCR → 交织合并。

        Args:
            col_gray: 列灰度图（局部坐标）
            col_image: 列彩色图（局部坐标，用于 OCR）
            regions: 投影分割区域（局部坐标）
            jiazhu_ranges: 夹注区域索引范围 [(start, end), ...]，inclusive
            col_top: 列顶部 y（全图坐标）
            col_bottom: 列底部 y（全图坐标）
            expected_chars: 每列预期字符数
            theoretical_char_h: 正文理论字高
            y_offset: 局部坐标到全图坐标的 y 偏移
            col_width: 列宽度（像素）

        Returns:
            (cells, ocr_text, jiazhu_info):
                cells: 合并后的 cell 列表
                ocr_text: 拼接的 OCR 文字
                jiazhu_info: 夹注区域信息列表（含 split_x）
        """
        segments = self._segment_column(regions, jiazhu_ranges)
        final_cells: list[dict] = []
        all_ocr_text: list[str] = []
        slot_idx = 0
        jiazhu_info: list[dict] = []

        for seg_type, region_indices in segments:
            seg_regions = [regions[i] for i in region_indices]

            if seg_type == "normal":
                # ── 正文段 ──
                # 裁剪段区域的图像做 OCR
                seg_y_top = seg_regions[0][0]
                seg_y_bot = seg_regions[-1][1]
                seg_image = col_image[seg_y_top:seg_y_bot, :]
                seg_text, seg_words = self._ocr_column_words(
                    seg_image, y_offset + seg_y_top)

                all_ocr_text.append(seg_text)

                # 逐区域匹配 OCR 文字
                # 将 seg_words 按 center_y 分配给最近的 region
                char_list = ([w.text for w in seg_words] if seg_words
                             else list(seg_text))
                char_idx = 0

                for r_top, r_bot in seg_regions:
                    text_char = (char_list[char_idx]
                                 if char_idx < len(char_list) else None)
                    if text_char is not None:
                        char_idx += 1

                    final_cells.append({
                        "type": "char" if text_char else "empty",
                        "index": slot_idx,
                        "y_top": round(float(r_top + y_offset), 2),
                        "y_bottom": round(float(r_bot + y_offset), 2),
                        "text": text_char,
                        "confidence": 1.0 if text_char else 0.0,
                    })
                    slot_idx += 1

            else:
                # ── 夹注段 ──
                jz_y_top = seg_regions[0][0]
                jz_y_bot = seg_regions[-1][1]

                left_sub, right_sub, split_x = self._split_jiazhu_subcols(
                    col_gray, jz_y_top, jz_y_bot, col_width)

                # 记录夹注区域信息（含 split_x）
                jiazhu_info.append({
                    "region_start": region_indices[0],
                    "region_end": region_indices[-1],
                    "y_top": int(y_offset + jz_y_top),
                    "y_bottom": int(y_offset + jz_y_bot),
                    "split_x": int(split_x),
                })

                # 夹注字高约为正文的 60-70%
                jiazhu_char_h = theoretical_char_h * 0.65

                # 右子列（sub_col=1，先读）
                right_cells = self._ocr_subcol(
                    right_sub, col_image[jz_y_top:jz_y_bot, split_x:],
                    jiazhu_char_h, y_offset + jz_y_top)

                # 左子列（sub_col=2，后读）
                left_cells = self._ocr_subcol(
                    left_sub, col_image[jz_y_top:jz_y_bot, :split_x],
                    jiazhu_char_h, y_offset + jz_y_top)

                all_ocr_text.append(
                    "".join(c.get("text", "") or "" for c in right_cells))
                all_ocr_text.append(
                    "".join(c.get("text", "") or "" for c in left_cells))

                # 按行交织合并：同一 index 的右(sub_col=1)和左(sub_col=2)
                n_rows = max(len(right_cells), len(left_cells))
                for i in range(n_rows):
                    idx = slot_idx + i
                    if i < len(right_cells):
                        cell = right_cells[i]
                        cell.update(type="jiazhu", index=idx, sub_col=1)
                        final_cells.append(cell)
                    if i < len(left_cells):
                        cell = left_cells[i]
                        cell.update(type="jiazhu", index=idx, sub_col=2)
                        final_cells.append(cell)
                slot_idx += n_rows

        # 添加 margin（首尾与 col_top/col_bottom 的间隙）
        col_height = col_bottom - col_top
        char_h = col_height / expected_chars if expected_chars > 0 else theoretical_char_h
        margin_max = char_h * self.MARGIN_MAX_RATIO

        if final_cells:
            first_top = final_cells[0]["y_top"]
            last_bot = final_cells[-1]["y_bottom"]

            top_gap = first_top - col_top
            if top_gap > 1:
                if top_gap <= margin_max:
                    final_cells.insert(0, {
                        "type": "margin",
                        "y_top": round(col_top, 2),
                        "y_bottom": round(first_top, 2),
                    })
                else:
                    final_cells[0]["y_top"] = round(col_top, 2)

            bot_gap = col_bottom - last_bot
            if bot_gap > 1:
                if bot_gap <= margin_max:
                    final_cells.append({
                        "type": "margin",
                        "y_top": round(last_bot, 2),
                        "y_bottom": round(col_bottom, 2),
                    })
                else:
                    final_cells[-1]["y_bottom"] = round(col_bottom, 2)

        ocr_text = "".join(all_ocr_text)
        return final_cells, ocr_text, jiazhu_info

    def _ocr_subcol(
        self,
        sub_gray: np.ndarray,
        sub_image: np.ndarray,
        jiazhu_char_h: float,
        y_offset: float,
    ) -> list[dict]:
        """对单个夹注子列做投影分割 + OCR + 逐区域匹配。

        Args:
            sub_gray: 子列灰度图
            sub_image: 子列彩色图（用于 OCR）
            jiazhu_char_h: 夹注理论字高
            y_offset: 子列顶部在全图中的 y 坐标

        Returns:
            cell 列表（无 index，由调用方设置）
        """
        if sub_gray.shape[0] < 5 or sub_gray.shape[1] < 5:
            return []

        # 投影分割
        sub_regions = self._projection_segment(sub_gray, jiazhu_char_h)
        if not sub_regions:
            return []

        # OCR
        sub_text, sub_words = self._ocr_column_words(sub_image, y_offset)

        # 逐区域匹配
        char_list = ([w.text for w in sub_words] if sub_words
                     else list(sub_text))
        char_idx = 0
        cells: list[dict] = []

        for r_top, r_bot in sub_regions:
            text_char = (char_list[char_idx]
                         if char_idx < len(char_list) else None)
            if text_char is not None:
                char_idx += 1

            cells.append({
                "type": "char" if text_char else "empty",
                "y_top": round(float(r_top + y_offset), 2),
                "y_bottom": round(float(r_bot + y_offset), 2),
                "text": text_char,
                "confidence": 1.0 if text_char else 0.0,
            })

        return cells

    # ─── 网格构建 ──────────────────────────────────────────

    # 间距超过此倍理论字高，视为断裂（后续区域为噪点）
    GAP_BREAK_RATIO = 3.0

    def _filter_regions(
        self,
        regions: list[tuple[int, int]],
        ocr_text: str,
        theoretical_char_h: float,
    ) -> list[tuple[int, int]]:
        """过滤投影区域中的噪点，保留真正的字符区域。

        两步过滤：
        1. 按间距断裂分组（gap > GAP_BREAK_RATIO × 字高）
        2. 选最佳组：优先匹配 OCR 字符数，其次选区域最多的组
        """
        if len(regions) <= 1:
            return regions

        # ── 按间距断裂分组 ──
        max_gap = theoretical_char_h * self.GAP_BREAK_RATIO
        groups: list[list[tuple[int, int]]] = [[regions[0]]]
        for i in range(1, len(regions)):
            gap = regions[i][0] - regions[i - 1][1]
            if gap > max_gap:
                groups.append([])
            groups[-1].append(regions[i])

        if len(groups) == 1:
            return groups[0]

        # ── 选最佳组 ──
        n_ocr = len(ocr_text)

        if n_ocr > 0:
            # 有 OCR 结果时：优先选区域数最接近 OCR 字符数的组
            # 平局时选区域数更多的（宁多勿少），再平局选总高度最大的
            def group_score(g: list) -> tuple:
                n = len(g)
                diff = abs(n - n_ocr)
                span = g[-1][1] - g[0][0]
                return (-diff, n, span)

            best_group = max(groups, key=group_score)
        else:
            # 无 OCR 结果：选区域数最多的组
            best_group = max(groups,
                             key=lambda g: (len(g), g[-1][1] - g[0][0]))

        return best_group

    # margin 不超过此比率 × char_height
    MARGIN_MAX_RATIO = 0.5

    def _build_char_grid(
        self,
        regions: list[tuple[int, int]],
        ocr_text: str,
        word_boxes: list[WordBox],
        col_top: float,
        col_bottom: float,
        expected_chars: int,
        theoretical_char_h: float,
    ) -> tuple[list[dict], float]:
        """融合投影分割区域、OCR 文字和先验约束，生成字符网格。

        三种格子类型，互不重叠：
        - "char": 有文字，y_top/y_bottom 来自 OCR word box 或投影分割
        - "empty": 空白字符格，连续等高无缝隙，占字符数
        - "margin": 列首/列尾边距，不占字符数

        铁律：
        1. char + empty = expected_chars（精确等于 21）
        2. 格子严格不重叠、不超出 [col_top, col_bottom]
        3. margin + empty + char 合起来精确填满 [col_top, col_bottom]
           （char 之间的缝隙除外）
        4. margin 高度不超过 MARGIN_MAX_RATIO × char_height
        """
        # 投影分割 + 过滤
        regions = self._filter_regions(
            regions, ocr_text, theoretical_char_h)
        regions = self._clip_regions(regions, col_top, col_bottom)

        # 融合投影区域和 OCR word box
        if word_boxes:
            # 始终融合：word box 决定字符数量和归属，投影提供精确边界
            regions = self._fuse_projection_and_ocr(regions, word_boxes)
        else:
            # 无 word box，回退到按 OCR 字符数等分大区域
            n_ocr = len(ocr_text)
            if n_ocr > 0 and len(regions) < n_ocr:
                regions = self._refine_regions_by_ocr(
                    regions, n_ocr, theoretical_char_h)

        n_regions = len(regions)

        col_height = col_bottom - col_top
        # char_height = 整个列高 / expected_chars，保证正好填满
        char_h = col_height / expected_chars
        margin_max = char_h * self.MARGIN_MAX_RATIO

        if n_regions == 0:
            # 整列无文字：全部 empty，从 col_top 到 col_bottom 等分
            cells: list[dict] = []
            for i in range(expected_chars):
                cells.append({
                    "type": "empty",
                    "index": i,
                    "y_top": round(col_top + i * char_h, 2),
                    "y_bottom": round(col_top + (i + 1) * char_h, 2),
                    "text": None,
                    "confidence": 0.0,
                })
            return cells, char_h

        # 截断过多区域
        if n_regions > expected_chars:
            regions = regions[:expected_chars]
            n_regions = expected_chars

        # ── 确定每个投影区域对应哪个槽位 ──
        # 用第一个区域的中心点确定起始 slot，后续区域连续递增。
        # 这样 N 个投影区域占用连续 N 个 slot，避免因区域偏大而跳过 slot。
        first_center = (regions[0][0] + regions[0][1]) / 2
        start_slot = int((first_center - col_top) / char_h)
        start_slot = max(0, min(expected_chars - n_regions, start_slot))

        slot_assignments: dict[int, int] = {}  # slot_index → region_index
        for ri in range(n_regions):
            slot = start_slot + ri
            if slot < expected_chars:
                slot_assignments[slot] = ri

        # ── 构建 cells 列表（21 个 char/empty + margin） ──
        cells = []
        # 用 word_boxes 的文字（更准确）或回退到 ocr_text 拆分
        ocr_chars = ([w.text for w in word_boxes] if word_boxes
                     else list(ocr_text))
        ocr_idx = 0

        i = 0
        while i < expected_chars:
            if i in slot_assignments:
                # ── char 槽位 ──
                ri = slot_assignments[i]
                r_top, r_bot = regions[ri]
                text_char = ocr_chars[ocr_idx] if ocr_idx < len(ocr_chars) else None
                ocr_idx += 1

                cells.append({
                    "type": "char",
                    "index": i,
                    "y_top": round(float(r_top), 2),
                    "y_bottom": round(float(r_bot), 2),
                    "text": text_char,
                    "confidence": 1.0 if text_char else 0.0,
                })
                i += 1
            else:
                # ── empty 段：连续的空槽位 ──
                empty_start = i
                while i < expected_chars and i not in slot_assignments:
                    i += 1
                n_empty = i - empty_start
                block_top = col_top + empty_start * char_h
                for j in range(n_empty):
                    cells.append({
                        "type": "empty",
                        "index": empty_start + j,
                        "y_top": round(block_top + j * char_h, 2),
                        "y_bottom": round(block_top + (j + 1) * char_h, 2),
                        "text": None,
                        "confidence": 0.0,
                    })

        # ── 消除重叠：相邻格子之间不得重叠 ──
        self._resolve_overlaps(cells)

        # ── 添加 margin：填补 col_top/col_bottom 与格子边缘的间隙 ──
        # 找第一个非 margin 格子的 y_top 和最后一个的 y_bottom
        if cells:
            first_cell_top = cells[0]["y_top"]
            last_cell_bottom = cells[-1]["y_bottom"]

            # 顶部 margin
            top_margin_h = first_cell_top - col_top
            if top_margin_h > 1:
                if top_margin_h <= margin_max:
                    cells.insert(0, {
                        "type": "margin",
                        "y_top": round(col_top, 2),
                        "y_bottom": round(first_cell_top, 2),
                    })
                else:
                    # margin 过大：把第一个格子的 y_top 拉到 col_top
                    cells[0]["y_top"] = round(col_top, 2)

            # 底部 margin
            bottom_margin_h = col_bottom - last_cell_bottom
            if bottom_margin_h > 1:
                if bottom_margin_h <= margin_max:
                    cells.append({
                        "type": "margin",
                        "y_top": round(last_cell_bottom, 2),
                        "y_bottom": round(col_bottom, 2),
                    })
                else:
                    # margin 过大：把最后一个格子的 y_bottom 拉到 col_bottom
                    cells[-1]["y_bottom"] = round(col_bottom, 2)

        return cells, char_h

    @staticmethod
    def _clip_regions(
        regions: list[tuple[int, int]],
        col_top: float,
        col_bottom: float,
    ) -> list[tuple[int, int]]:
        """裁剪投影区域到 [col_top, col_bottom] 范围内。"""
        clipped = []
        for r_top, r_bot in regions:
            r_top = max(r_top, col_top)
            r_bot = min(r_bot, col_bottom)
            if r_bot - r_top >= 5:  # 裁剪后至少 5px
                clipped.append((r_top, r_bot))
        return clipped

    def _refine_regions_by_ocr(
        self,
        regions: list[tuple[float, float]],
        n_ocr: int,
        theoretical_char_h: float,
    ) -> list[tuple[float, float]]:
        """用 OCR 字符数校准投影区域：对偏大的区域做等分补充。

        当投影分割的区域数 < OCR 识别的字符数时，说明有些区域
        包含了多个字（投影法未能分开）。按区域大小降序，优先
        对最大的区域做等分，直到总区域数 = OCR 字符数。
        """
        result = list(regions)
        deficit = n_ocr - len(result)

        while deficit > 0:
            # 找最大的区域
            max_idx = max(range(len(result)),
                          key=lambda i: result[i][1] - result[i][0])
            r_top, r_bot = result[max_idx]
            r_h = r_bot - r_top

            # 该区域能容纳几个字？
            n_split = min(deficit + 1, max(2, round(r_h / theoretical_char_h)))
            if n_split <= 1 or r_h < theoretical_char_h * 1.2:
                break  # 不再可分

            # 等分
            sub_regions = []
            for i in range(n_split):
                sub_top = r_top + i * r_h / n_split
                sub_bot = r_top + (i + 1) * r_h / n_split
                sub_regions.append((sub_top, sub_bot))

            result[max_idx:max_idx + 1] = sub_regions
            deficit = n_ocr - len(result)

        return result

    # 投影区域比匹配的 word box 大超过此比率时，修剪到 word box 边界
    TRIM_EXPAND_RATIO = 1.8

    @staticmethod
    def _fuse_projection_and_ocr(
        regions: list[tuple[float, float]],
        word_boxes: list[WordBox],
    ) -> list[tuple[float, float]]:
        """融合投影区域和 OCR word box，生成最终字符区域。

        核心思想：
        - OCR word box 决定有几个字、每个字的大致位置
        - 投影区域提供精确的像素边界
        - 每个投影区域优先分配给其中心点落在 y 范围内的 word box
        - 若无覆盖的 word box，回退到最近中心点分配
        - 每个 word box 取其匹配投影区域的并集，并确保至少覆盖 word box 范围

        这解决了：
        a) 投影把 "三" 等字拆成多个区域 → word box 范围覆盖合并
        b) 投影把边框线和字符连成一片 → 不在任何 word box 范围内的不被分配
        """
        if not word_boxes:
            return list(regions)

        wbs = sorted(word_boxes, key=lambda w: w.center_y)

        # Step 1: 每个投影区域分配给 word box
        wb_regions: dict[int, list[tuple[float, float]]] = {
            i: [] for i in range(len(wbs))
        }

        for r_top, r_bot in regions:
            r_center = (r_top + r_bot) / 2

            # 优先：找中心点落在 word box y 范围内的
            covered = [i for i, wb in enumerate(wbs)
                       if wb.y_min <= r_center <= wb.y_max]

            if len(covered) == 1:
                wb_regions[covered[0]].append((r_top, r_bot))
            elif len(covered) > 1:
                # 多个 word box 覆盖此区域，选最近的
                best = min(covered, key=lambda i: abs(r_center - wbs[i].center_y))
                wb_regions[best].append((r_top, r_bot))
            else:
                # 没有覆盖的 word box，回退到最近中心点
                best_idx = min(range(len(wbs)),
                               key=lambda i: abs(r_center - wbs[i].center_y))
                # 但距离太远的不分配（超过 1.5 倍字高视为噪点）
                if wbs:
                    median_h = float(np.median([w.height for w in wbs]))
                    dist = abs(r_center - wbs[best_idx].center_y)
                    if dist <= median_h * 1.5:
                        wb_regions[best_idx].append((r_top, r_bot))
                    # else: 丢弃（边框线等噪点）

        # Step 2: 每个 word box 的区域 = 投影并集 ∪ word box 范围
        result = []
        for i, wb in enumerate(wbs):
            matched = wb_regions[i]
            if matched:
                # 取投影并集，并确保覆盖 word box 范围
                fused_top = min(min(r[0] for r in matched), wb.y_min)
                fused_bot = max(max(r[1] for r in matched), wb.y_max)
                result.append((fused_top, fused_bot))
            else:
                # 没有匹配的投影区域，回退到 word box 坐标
                result.append((wb.y_min, wb.y_max))

        return result

    @staticmethod
    def _resolve_overlaps(cells: list[dict]) -> None:
        """消除相邻格子之间的重叠。

        当 char 格子比网格槽位大时，可能和相邻 empty 格子重叠。
        规则：char 的位置不变，调整 empty 的边界避让 char。
        如果调整后 empty 高度 < 1px，删除该 empty。
        """
        # 按 index（char/empty）排序，margin 不参与
        indexed = [c for c in cells if c.get("index") is not None]
        indexed.sort(key=lambda c: c["index"])

        for j in range(len(indexed) - 1):
            curr = indexed[j]
            nxt = indexed[j + 1]
            overlap = curr["y_bottom"] - nxt["y_top"]
            if overlap > 0:
                # 调整 empty 的边界
                if curr["type"] == "empty" and nxt["type"] == "char":
                    curr["y_bottom"] = round(nxt["y_top"], 2)
                elif curr["type"] == "char" and nxt["type"] == "empty":
                    nxt["y_top"] = round(curr["y_bottom"], 2)
                elif curr["type"] == "empty" and nxt["type"] == "empty":
                    # 两个 empty 重叠：收缩后者
                    nxt["y_top"] = round(curr["y_bottom"], 2)
                # char-char 重叠：保持不变（投影数据优先）

        # 确保所有格子高度 >= 0（被完全覆盖的 empty 置为 0 高度保留编号）
        for c in cells:
            if c["y_bottom"] < c["y_top"]:
                c["y_bottom"] = c["y_top"]

    @staticmethod
    def _has_significant_overlap(
        cells: list[dict],
        theoretical_char_h: float,
    ) -> bool:
        """检查 char 类型 cells 是否有显著 y 坐标重叠。

        若相邻 char 的 y 坐标重叠超过理论字高的 30%，
        说明该列可能是夹注漏检，应回退到夹注处理路径。
        """
        chars = sorted(
            [c for c in cells if c["type"] == "char"],
            key=lambda c: c["y_top"],
        )
        if len(chars) < 2:
            return False
        threshold = theoretical_char_h * 0.3
        for i in range(len(chars) - 1):
            overlap = chars[i]["y_bottom"] - chars[i + 1]["y_top"]
            if overlap > threshold:
                return True
        return False

    def _estimate_char_height_from_regions(
        self,
        regions: list[tuple[int, int]],
        theoretical_char_h: float,
    ) -> float:
        """从投影分割区域的间距估算实际字高。"""
        if len(regions) < 2:
            return theoretical_char_h

        centers = [(r[0] + r[1]) / 2 for r in regions]
        gaps = [centers[i + 1] - centers[i] for i in range(len(centers) - 1)]

        reasonable = [g for g in gaps
                      if theoretical_char_h * 0.4 < g < theoretical_char_h * 2.0]

        if not reasonable:
            return theoretical_char_h

        median_gap = float(np.median(reasonable))

        min_h = theoretical_char_h * self.CHAR_HEIGHT_MIN_RATIO
        max_h = theoretical_char_h * self.CHAR_HEIGHT_MAX_RATIO
        return float(np.clip(median_gap, min_h, max_h))

    @staticmethod
    def _empty_column(
        col_idx: int,
        left_x: float,
        right_x: float,
        col_top: float,
        col_bottom: float,
        expected_chars: int,
    ) -> dict:
        """生成空列结果。"""
        return {
            "index": col_idx,
            "left_x": left_x,
            "right_x": right_x,
            "ocr_text": "",
            "cells": [{
                "type": "margin",
                "y_top": round(col_top, 2),
                "y_bottom": round(col_bottom, 2),
            }],
        }
