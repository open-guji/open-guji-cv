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

            if x2 <= x1 or y2 <= y1:
                result_columns.append(self._empty_column(
                    col_idx, left_x, right_x, col_top, col_bottom, expected_chars))
                continue

            col_gray = gray[y1:y2, x1:x2]

            # Step 1: 投影法分割字符区域
            regions = self._projection_segment(col_gray, theoretical_char_h)

            # Step 2: 局部坐标 → 全图坐标（确保 Python int）
            regions = [(int(y1 + r_top), int(y1 + r_bot)) for r_top, r_bot in regions]

            # Step 3: OCR 识别整列文字（含每字位置）
            col_image = image[y1:y2, x1:x2]
            ocr_text, word_boxes = self._ocr_column_words(col_image, y1)

            # Step 4: 构建字符网格
            cells, char_h = self._build_char_grid(
                regions, ocr_text, word_boxes,
                col_top, col_bottom, expected_chars,
                theoretical_char_h)

            if char_h > 0:
                all_char_heights.append(char_h)

            result_columns.append({
                "index": col_idx,
                "left_x": left_x,
                "right_x": right_x,
                "ocr_text": ocr_text,
                "cells": cells,
            })

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
