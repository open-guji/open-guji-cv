"""正文区域检测器：页边距检测 + 外边框定位。

两步定位正文区域：
1. 页边距检测 — 找到四边的均匀背景区域（白/黑/其他），缩小到书页范围
2. 外边框检测 — 在书页范围内找到正文外边框矩形，定位正文区域

输出 FrameInfo：包含页边距、外边框位置、正文区域坐标。
"""

import cv2
import numpy as np
from dataclasses import dataclass


@dataclass
class MarginInfo:
    """四边页边距信息。"""
    top: int = 0       # 上边距像素数
    bottom: int = 0    # 下边距像素数
    left: int = 0      # 左边距像素数
    right: int = 0     # 右边距像素数
    color: str = "none"  # 页边距颜色: "white" / "black" / "other" / "none"


@dataclass
class FrameInfo:
    """正文区域定位结果。"""
    # 原始图片尺寸
    img_h: int = 0
    img_w: int = 0
    # Step 1: 页边距（书页在图片中的范围）
    margin: MarginInfo = None
    # Step 2: 外边框位置（正文在书页中的范围）
    border_top: int = 0
    border_bottom: int = 0
    border_left: int = 0
    border_right: int = 0
    # 正文区域（最终的内容区域坐标，相对于原图）
    content_top: int = 0
    content_bottom: int = 0
    content_left: int = 0
    content_right: int = 0

    def __post_init__(self):
        if self.margin is None:
            self.margin = MarginInfo()


class FrameDetector:
    """正文区域检测器。"""

    # ═══════════════ Step 1: 页边距检测 ═══════════════

    # 页边距检测参数
    MARGIN_SCAN_RATIO = 0.15      # 从边缘扫描最多 15%（避免扫入天头文字）
    MARGIN_UNIFORMITY_THRESH = 20  # 标准差 < 此值视为均匀区域（更严格）
    MARGIN_DIFF_THRESH = 30       # 边缘与内容亮度差 > 此值才算页边距

    @classmethod
    def detect_margin(cls, img: np.ndarray) -> MarginInfo:
        """检测四边的页边距。

        方法：从每条边向内扫描，逐行/列计算亮度标准差。
        当标准差突然增大（遇到文字/边框）时，标记为页边距结束。
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape

        margin = MarginInfo()
        margin.top = cls._scan_margin_from_edge(gray, "top")
        margin.bottom = cls._scan_margin_from_edge(gray, "bottom")
        margin.left = cls._scan_margin_from_edge(gray, "left")
        margin.right = cls._scan_margin_from_edge(gray, "right")

        # 判断页边距颜色
        margin.color = cls._classify_margin_color(gray, margin)

        return margin

    @classmethod
    def _scan_margin_from_edge(cls, gray: np.ndarray, side: str) -> int:
        """从指定边向内扫描，找到页边距结束位置。

        页边距特征：
        1. 每行/列的像素值标准差很低（均匀的背景）
        2. 亮度与图片中心区域有明显差异（区分拍照背景 vs 天头空白）

        遇到文字或边框时标准差突然增大。
        """
        h, w = gray.shape
        max_scan = int((h if side in ("top", "bottom") else w) * cls.MARGIN_SCAN_RATIO)

        # 取中间 60% 的横截面来计算（避免角落干扰）
        if side in ("top", "bottom"):
            x0, x1 = int(w * 0.2), int(w * 0.8)
        else:
            y0, y1 = int(h * 0.2), int(h * 0.8)

        # 先计算图片中心区域的平均亮度作为参考
        center = gray[h // 3: 2 * h // 3, w // 3: 2 * w // 3]
        center_mean = float(np.mean(center))

        margin_size = 0
        for i in range(max_scan):
            if side == "top":
                row = gray[i, x0:x1]
            elif side == "bottom":
                row = gray[h - 1 - i, x0:x1]
            elif side == "left":
                row = gray[y0:y1, i]
            else:  # right
                row = gray[y0:y1, w - 1 - i]

            std = float(np.std(row))
            mean = float(np.mean(row))

            # 需要同时满足：均匀（低 std）+ 和中心亮度有差异
            if std > cls.MARGIN_UNIFORMITY_THRESH:
                break
            if abs(mean - center_mean) < cls.MARGIN_DIFF_THRESH:
                break  # 亮度和中心一样 → 这是天头/地脚，不是拍照背景

            margin_size = i + 1

        return margin_size

    @classmethod
    def _classify_margin_color(cls, gray: np.ndarray, margin: MarginInfo) -> str:
        """根据页边距区域的亮度判断颜色。"""
        h, w = gray.shape
        samples = []

        if margin.top > 5:
            samples.append(float(np.mean(gray[:margin.top, :])))
        if margin.bottom > 5:
            samples.append(float(np.mean(gray[h - margin.bottom:, :])))
        if margin.left > 5:
            samples.append(float(np.mean(gray[:, :margin.left])))
        if margin.right > 5:
            samples.append(float(np.mean(gray[:, w - margin.right:])))

        if not samples:
            return "none"

        avg_brightness = np.mean(samples)
        if avg_brightness > 200:
            return "white"
        if avg_brightness < 60:
            return "black"
        return "other"

    # ═══════════════ Step 2: 外边框检测 ═══════════════

    # 边框检测参数
    BORDER_LINE_RATIO = 0.15  # 线条至少占 15% 的高度/宽度（古籍边框常有磨损）

    @classmethod
    def detect_frame(cls, img: np.ndarray, margin: MarginInfo = None,
                     debug_dir: str = None) -> FrameInfo:
        """检测正文外边框，返回完整的 FrameInfo。

        Args:
            img: BGR 彩色图片
            margin: 已检测的页边距（None 则自动检测）
            debug_dir: debug 输出目录（None 则不输出）
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape

        info = FrameInfo(img_h=h, img_w=w)

        # Step 1: 页边距
        if margin is None:
            margin = cls.detect_margin(img)
        info.margin = margin

        # 去掉页边距后的书页区域
        page_top = margin.top
        page_bottom = h - margin.bottom
        page_left = margin.left
        page_right = w - margin.right

        if page_bottom - page_top < 50 or page_right - page_left < 50:
            # 页面太小，用整张图
            page_top, page_bottom = 0, h
            page_left, page_right = 0, w

        page = gray[page_top:page_bottom, page_left:page_right]
        ph, pw = page.shape

        # Step 2: 在书页范围内找外边框
        _, bw = cv2.threshold(page, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # 彩色栏线补充（红/蓝栏线在灰度 Otsu 下不可见）
        if len(img.shape) == 3:
            page_color = img[page_top:page_bottom, page_left:page_right]
            color_mask = cls._extract_color_line_mask(page_color)
            bw = cv2.bitwise_or(bw, color_mask)

        # 提取长水平线（多尺度：从严到松，取并集）
        h_lines = np.zeros_like(bw)
        for div in [8, 16]:
            kl = max(pw // div, 15)
            kk = cv2.getStructuringElement(cv2.MORPH_RECT, (kl, 1))
            h_lines = cv2.bitwise_or(h_lines, cv2.morphologyEx(bw, cv2.MORPH_OPEN, kk))

        # 提取长垂直线（多尺度）
        v_lines = np.zeros_like(bw)
        for div in [6, 10]:
            kl = max(ph // div, 15)
            kk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kl))
            v_lines = cv2.bitwise_or(v_lines, cv2.morphologyEx(bw, cv2.MORPH_OPEN, kk))

        # 找水平线的 y 位置（上下边框）
        h_proj = np.sum(h_lines, axis=1) / 255
        h_threshold = pw * cls.BORDER_LINE_RATIO

        # skip 区域：有 margin 时跳过少一点（margin 已经排除了背景）
        skip_h = max(int(ph * 0.01), 2)

        border_top_local = cls._find_border_line(
            page, h_proj, h_threshold, ph, skip_h, from_start=True, axis="h")
        border_bottom_local = cls._find_border_line(
            page, h_proj, h_threshold, ph, skip_h, from_start=False, axis="h")

        info.border_top = page_top + (border_top_local if border_top_local is not None else int(ph * 0.05))
        info.border_bottom = page_top + (border_bottom_local if border_bottom_local is not None else int(ph * 0.95))

        # 找垂直线的 x 位置（左右边框）
        v_proj = np.sum(v_lines, axis=0) / 255
        v_threshold = ph * cls.BORDER_LINE_RATIO
        skip_w = max(int(pw * 0.01), 2)

        border_left_local = cls._find_border_line(
            page, v_proj, v_threshold, pw, skip_w, from_start=True, axis="v")
        border_right_local = cls._find_border_line(
            page, v_proj, v_threshold, pw, skip_w, from_start=False, axis="v")

        info.border_left = page_left + (border_left_local if border_left_local is not None else int(pw * 0.05))
        info.border_right = page_left + (border_right_local if border_right_local is not None else int(pw * 0.95))

        # 正文区域 = 边框内侧（往内缩几个像素避开边框线本身）
        border_w = max((info.border_right - info.border_left) // 100, 3)
        info.content_top = info.border_top + border_w
        info.content_bottom = info.border_bottom - border_w
        info.content_left = info.border_left + border_w
        info.content_right = info.border_right - border_w

        # Debug 输出
        if debug_dir:
            cls._save_debug(img, info, debug_dir)

        return info

    @classmethod
    def _find_border_line(cls, page: np.ndarray, morph_proj: np.ndarray,
                          morph_threshold: float, length: int, skip: int,
                          from_start: bool, axis: str) -> int | None:
        """找边框线位置：先用形态学投影，失败则用行/列均值的暗线检测。

        Args:
            page: 灰度书页图片
            morph_proj: 形态学投影（h_proj 或 v_proj）
            morph_threshold: 形态学阈值
            length: 搜索范围（ph 或 pw）
            skip: 跳过边缘像素数
            from_start: True=从起始端搜索, False=从末端搜索
            axis: "h"=水平线(搜索y), "v"=垂直线(搜索x)
        """
        half = length // 2
        search_range = range(skip, half) if from_start else range(length - 1 - skip, half, -1)

        # 方法1：形态学投影
        for i in search_range:
            if morph_proj[i] > morph_threshold:
                return i

        # 方法2 fallback：行/列均值的暗线检测
        # 边框线在行/列均值中表现为明显的暗值（比周围低很多）
        if axis == "h":
            line_means = np.mean(page, axis=1)
        else:
            line_means = np.mean(page, axis=0)

        overall_mean = float(np.mean(line_means[length // 4: 3 * length // 4]))
        dark_threshold = overall_mean - 40  # 比内容区域暗 40+ 灰度

        for i in search_range:
            if line_means[i] < dark_threshold:
                return i

        return None

    @classmethod
    def extract_lines(cls, img: np.ndarray) -> np.ndarray:
        """提取所有直线（删除文字），返回只含直线的二值图。

        改进策略：
        1. 多阈值二值化（Otsu + 更高阈值）— 捕捉浅色细线
        2. 断线连接（先膨胀再开运算）— 补回磨损断裂的线段
        3. mask 回原图 — 避免膨胀引入的假像素
        4. 彩色栏线补充 — HSV 饱和度通道检测红/蓝栏线
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape

        # 多阈值二值化
        otsu_val, bw_otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        _, bw_high = cv2.threshold(gray, min(int(otsu_val * 1.5), 200), 255, cv2.THRESH_BINARY_INV)
        bw = cv2.bitwise_or(bw_otsu, bw_high)

        # 彩色栏线（红/蓝）补充到 bw
        if len(img.shape) == 3:
            color_mask = cls._extract_color_line_mask(img)
            bw = cv2.bitwise_or(bw, color_mask)

        lines = np.zeros_like(bw)

        # 垂直线：膨胀连接断点 → 开运算提取 → mask 回原图
        for div in [4, 6, 10, 15, 25]:
            kl = max(h // div, 8)
            gap = min(kl // 10, 15)
            dk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(gap, 2)))
            bw_d = cv2.dilate(bw, dk, iterations=1)
            vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kl))
            vl = cv2.morphologyEx(bw_d, cv2.MORPH_OPEN, vk)
            lines = cv2.bitwise_or(lines, cv2.bitwise_and(vl, bw))

        # 水平线
        for div in [4, 8, 16]:
            kl = max(w // div, 8)
            gap = min(kl // 10, 15)
            dk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(gap, 2), 1))
            bw_d = cv2.dilate(bw, dk, iterations=1)
            hk = cv2.getStructuringElement(cv2.MORPH_RECT, (kl, 1))
            hl = cv2.morphologyEx(bw_d, cv2.MORPH_OPEN, hk)
            lines = cv2.bitwise_or(lines, cv2.bitwise_and(hl, bw))

        return lines

    @classmethod
    def _extract_color_line_mask(cls, img: np.ndarray) -> np.ndarray:
        """用 HSV 饱和度+色相通道检测彩色（红/蓝）栏线，返回二值掩码。

        红色栏线：H 在 [0,10] 或 [160,180]，S > 80，V > 60
        蓝色栏线：H 在 [100,130]，S > 80，V > 60
        饱和度兜底：S > 120 的高饱和区域也纳入
        """
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h_ch, s_ch, v_ch = cv2.split(hsv)

        # 红色（色相环两端）
        red_lo1 = cv2.inRange(hsv, (0, 80, 60), (10, 255, 255))
        red_lo2 = cv2.inRange(hsv, (160, 80, 60), (180, 255, 255))
        red_mask = cv2.bitwise_or(red_lo1, red_lo2)

        # 蓝色
        blue_mask = cv2.inRange(hsv, (100, 80, 60), (130, 255, 255))

        # 饱和度兜底（捕捉其他颜色栏线）
        _, sat_mask = cv2.threshold(s_ch, 120, 255, cv2.THRESH_BINARY)
        # 饱和度兜底需配合亮度限制（排除高亮反光）
        _, v_mask = cv2.threshold(v_ch, 50, 255, cv2.THRESH_BINARY)
        sat_mask = cv2.bitwise_and(sat_mask, v_mask)

        return cv2.bitwise_or(cv2.bitwise_or(red_mask, blue_mask), sat_mask)

    @classmethod
    def _save_debug(cls, img: np.ndarray, info: FrameInfo, debug_dir: str):
        """输出 annotated debug 图片。"""
        from pathlib import Path
        Path(debug_dir).mkdir(parents=True, exist_ok=True)

        vis = img.copy() if len(img.shape) == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        h, w = vis.shape[:2]
        m = info.margin

        # 画页边距区域（半透明蓝色覆盖）
        overlay = vis.copy()
        margin_color = (255, 200, 100)  # 浅蓝色
        if m.top > 0:
            cv2.rectangle(overlay, (0, 0), (w, m.top), margin_color, -1)
        if m.bottom > 0:
            cv2.rectangle(overlay, (0, h - m.bottom), (w, h), margin_color, -1)
        if m.left > 0:
            cv2.rectangle(overlay, (0, 0), (m.left, h), margin_color, -1)
        if m.right > 0:
            cv2.rectangle(overlay, (w - m.right, 0), (w, h), margin_color, -1)
        cv2.addWeighted(overlay, 0.3, vis, 0.7, 0, vis)

        # 画外边框（红色矩形）
        cv2.rectangle(vis,
                      (info.border_left, info.border_top),
                      (info.border_right, info.border_bottom),
                      (0, 0, 255), 3)

        # 画正文区域（绿色矩形）
        cv2.rectangle(vis,
                      (info.content_left, info.content_top),
                      (info.content_right, info.content_bottom),
                      (0, 255, 0), 2)

        # 标注文字
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(vis, f"margin: T={m.top} B={m.bottom} L={m.left} R={m.right} ({m.color})",
                    (10, 30), font, 0.7, (0, 0, 255), 2)
        cv2.putText(vis, f"border: [{info.border_left},{info.border_top}]-[{info.border_right},{info.border_bottom}]",
                    (10, 60), font, 0.7, (0, 0, 255), 2)
        cv2.putText(vis, f"content: [{info.content_left},{info.content_top}]-[{info.content_right},{info.content_bottom}]",
                    (10, 90), font, 0.7, (0, 255, 0), 2)

        out_path = str(Path(debug_dir) / "frame_detect.png")
        cv2.imwrite(out_path, vis)

        # 输出直线提取图
        lines = cls.extract_lines(img)
        cv2.imwrite(str(Path(debug_dir) / "lines_only.png"), lines)
