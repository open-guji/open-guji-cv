"""内容区域边界检测 — 裁到正文区。

四方向裁切：
- 左右：LSD 检测垂直线段 → 聚类 → 找外框线位置
- 上下：从外框线向内找正文界栏线，裁掉天头/地脚

不依赖 deskew 是否已裁切 — 两种情况都能正确处理。
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

# 导入 border_detect 的聚类函数
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from border_detect import cluster_lines, _find_border_pair


# ── 上下方向：正文界栏线检测 ──
INNER_LINE_EDGE_RATIO = 0.15
INNER_LINE_SEARCH_MAX_TOP = 0.25    # 天头最大深度（天头较大，~16%）
INNER_LINE_SEARCH_MAX_BOTTOM = 0.10 # 地脚最大深度（地脚较小，~6%）
INNER_LINE_GAP_MIN = 30
INNER_LINE_PADDING = 3

# ── LSD 参数 ──
_MIN_LINE_LENGTH = 30
_ANGLE_TOL = 10.0

# ── 裁边外整列救援（2026-08-24 窄页专项）──
# 外框磨没时 LSD 只剩界行，最外结构线被当外框，整列字被裁掉（20 个
# 窄页的根因之一；另一半是扫描本身把列贴边/裁掉）。判据三层，实测
# 38 页（20 窄 + 18 健康）健康页零误触发：
# 1) 赤字闸：界内数得出的文字列 ≥ 预期列数就不救（版心在健康页的
#    行覆盖 0.7~0.98，光看窗口内容挡不住它——必须先确认缺列）；
# 2) 窗口证据：行覆盖 ≥0.45、密度 ∈[0.015,0.35]；
# 3) 行网格对齐：窗内行墨轮廓与界内行墨轮廓的相关 ≥0.40 ——真列的
#    字与界内同网格（实测 0.46~0.72），版心的题名/卷次/页码不对齐
#    （实测 -0.17~+0.31）。
# 贴图像边的墨：窗内墨宽 ≥0.55×列距按整列救到图像边（vol02 多页扫描
# 把第 9 列贴边裁进来）；窄条贴边（邻页残留）不救。
RESCUE_ROW_COV = 0.45
RESCUE_DENS_LO = 0.015
RESCUE_DENS_HI = 0.35
RESCUE_CORR = 0.40
RESCUE_EDGE_W = 0.55
RESCUE_PAD = 8
RESCUE_MAX_STEPS = 2
_PITCH_CLIP = (120.0, 300.0)


def find_content_bounds(gray: np.ndarray,
                        n_cols_expected: int | None = None
                        ) -> tuple[int, int, int, int]:
    """找到正文内容区的边界。

    Args:
        n_cols_expected: 每半页预期文字列数（profile.lines_per_page）。
            给定时启用裁边外整列救援（见上方常量注释）；None 关闭。

    Returns:
        (top, bottom, left, right) 像素坐标
    """
    h, w = gray.shape
    gray_u8 = gray.astype(np.uint8) if gray.dtype != np.uint8 else gray

    # ── 左右：LSD + 聚类找外框线 ──
    left, right, v_clusters = _find_lr_by_lsd(gray_u8, h, w)

    # ── 上下：外框线 + 正文界栏线 ──
    edges = cv2.Canny(gray_u8, 30, 100, apertureSize=3)
    content_w = right - left + 1

    # 先找水平外框线
    top_frame = _find_h_frame(edges, h, left, right, content_w, from_top=True)
    bottom_frame = _find_h_frame(edges, h, left, right, content_w, from_top=False)

    # 从外框线向内找正文界栏线
    top = _find_inner_line(edges, top_frame, h, left, right, content_w, from_top=True)
    bottom = _find_inner_line(edges, bottom_frame, h, left, right, content_w, from_top=False)

    if n_cols_expected:
        left, right = _rescue_cropped_columns(
            gray_u8, top, bottom, left, right, v_clusters, n_cols_expected)

    return top, bottom, left, right


def _cluster_pitch(v_clusters: list, left: int, right: int,
                   h: int) -> float | None:
    """结构竖线簇间距中位 ≈ 列距。证据不足返回 None（救援随之关闭）。"""
    from border_detect import _is_structural_line
    xs = sorted(c["intercept"] for c in v_clusters
                if _is_structural_line(c, h, 0.3)
                and left - 20 <= c["intercept"] <= right + 20)
    if len(xs) < 3:
        return None
    gaps = np.diff(xs)
    gaps = gaps[(gaps > _PITCH_CLIP[0] * 0.6) & (gaps < _PITCH_CLIP[1])]
    if len(gaps) == 0:
        return None
    return float(np.clip(np.median(gaps), *_PITCH_CLIP))


def _count_text_columns(binary_inner: np.ndarray, pitch: float) -> int:
    """界内文字列计数：竖投影平滑后数宽 ≥0.35×列距的墨带。"""
    colink = binary_inner.sum(axis=0).astype(float)
    sm = np.convolve(colink, np.ones(25) / 25, mode="same")
    on = sm > max(1.0, 0.12 * np.percentile(sm, 90))
    n = 0
    run = 0
    for v in on:
        if v:
            run += 1
        else:
            if run > 0.35 * pitch:
                n += 1
            run = 0
    if run > 0.35 * pitch:
        n += 1
    return n


def _rescue_cropped_columns(gray: np.ndarray, top: int, bottom: int,
                            left: int, right: int, v_clusters: list,
                            n_expected: int) -> tuple[int, int]:
    """外框磨没/扫描贴边时，把裁边外的整列文字救回来。判据见常量注释。"""
    pitch = _cluster_pitch(v_clusters, left, right, gray.shape[0])
    if pitch is None:
        return left, right
    binary = gray < 128
    H, W = gray.shape
    ct, cb = max(0, top), min(H, bottom)
    if cb - ct < 4 * pitch:
        return left, right
    if _count_text_columns(binary[ct:cb, left:right], pitch) >= n_expected:
        return left, right
    kern = np.ones(15) / 15
    inner_prof = np.convolve(
        binary[ct:cb, left + 40:max(left + 41, right - 40)]
        .sum(axis=1).astype(float), kern, "same")

    def extend(bound: int, direction: int) -> int:
        for _ in range(RESCUE_MAX_STEPS):
            if direction < 0:
                w0 = max(0, int(bound - pitch))
                w1 = max(0, int(bound - RESCUE_PAD))
            else:
                w0 = min(W, int(bound + RESCUE_PAD))
                w1 = min(W, int(bound + pitch))
            if w1 - w0 < 0.4 * pitch:
                return bound
            win = binary[ct:cb, w0:w1]
            rows = float((win.sum(axis=1) > 0).mean())
            dens = float(win.mean())
            nz = np.nonzero(win.sum(axis=0))[0]
            if rows < RESCUE_ROW_COV or not (RESCUE_DENS_LO <= dens
                                             <= RESCUE_DENS_HI) \
                    or not nz.size:
                return bound
            win_prof = np.convolve(win.sum(axis=1).astype(float), kern, "same")
            if win_prof.std() <= 0:
                return bound
            corr = float(np.corrcoef(inner_prof, win_prof)[0, 1])
            if not np.isfinite(corr) or corr < RESCUE_CORR:
                return bound
            ink_w = int(nz[-1] - nz[0]) + 1
            if direction < 0:
                lo = int(nz[0]) + w0
                if lo < RESCUE_PAD + 4:          # 墨贴图像边
                    return 0 if ink_w >= RESCUE_EDGE_W * pitch else bound
                bound = max(0, lo - RESCUE_PAD)
            else:
                hi = int(nz[-1]) + w0
                if hi > W - RESCUE_PAD - 4:
                    return W - 1 if ink_w >= RESCUE_EDGE_W * pitch else bound
                bound = min(W - 1, hi + RESCUE_PAD)
        return bound

    return extend(left, -1), extend(right, +1)


# ─── 左右方向：LSD + border_detect ────────────────────────


def _find_lr_by_lsd(gray: np.ndarray, h: int, w: int
                    ) -> tuple[int, int, list]:
    """用 LSD 检测垂直线段，聚类后找左右外框线。返回 (left, right, 竖簇)。"""
    lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    raw_lines, widths, _, _ = lsd.detect(gray)

    if raw_lines is None:
        return 0, w - 1, []

    v_segs = []
    for i, line in enumerate(raw_lines):
        x1, y1, x2, y2 = line[0]
        dx, dy = x2 - x1, y2 - y1
        length = np.sqrt(dx * dx + dy * dy)
        if length < _MIN_LINE_LENGTH:
            continue
        wd = float(widths[i][0]) if widths is not None else 1.0
        angle = abs(np.degrees(np.arctan2(abs(dx), abs(dy))))
        if angle <= _ANGLE_TOL:
            v_segs.append({
                "x1": float(x1), "y1": float(y1),
                "x2": float(x2), "y2": float(y2),
                "length": float(length), "width": wd, "type": "vertical",
            })

    if len(v_segs) < 2:
        return 0, w - 1, []

    v_clusters = cluster_lines(v_segs, "v", pos_tol=15, max_gap=60)

    left_pair = _find_border_pair(v_clusters, "min", h, w)
    right_pair = _find_border_pair(v_clusters, "max", h, w)

    left = int(left_pair["outer"]["intercept"]) if left_pair["outer"] else 0
    right = int(right_pair["outer"]["intercept"]) if right_pair["outer"] else w - 1

    # 安全检查：content 至少 50% 宽度
    if right - left < w * 0.5:
        return 0, w - 1, v_clusters

    return max(0, left), min(w - 1, right), v_clusters


# ─── 上下方向：水平外框线 + 正文界栏线 ─────────────────────


def _find_h_frame(
    edges: np.ndarray,
    h: int, col_left: int, col_right: int,
    content_w: int,
    from_top: bool,
) -> int:
    """找水平外框线（上/下边缘最近的强水平边缘行）。"""
    search_depth = int(h * 0.10)

    if from_top:
        for r in range(min(search_depth, h)):
            d = np.sum(edges[r, col_left:col_right + 1] > 0) / content_w
            if d >= 0.20:
                return r
        return 0
    else:
        for r in range(h - 1, max(h - search_depth, -1), -1):
            d = np.sum(edges[r, col_left:col_right + 1] > 0) / content_w
            if d >= 0.20:
                return r
        return h - 1


def _find_inner_line(
    edges: np.ndarray,
    frame_line: int,
    h: int,
    col_left: int, col_right: int,
    content_w: int,
    from_top: bool,
) -> int:
    """从外框线向内找正文界栏线。

    天头较大（~16% 高度），搜索范围宽。
    地脚较小（~6% 高度），搜索范围窄，避免把版心鱼尾横线
    （距外框线 ~31%）误认为界栏线。
    """
    if from_top:
        search_max = int(h * INNER_LINE_SEARCH_MAX_TOP)
        scan_start = frame_line + INNER_LINE_GAP_MIN
        scan_end = min(h, frame_line + search_max)
        for r in range(scan_start, scan_end):
            d = np.sum(edges[r, col_left:col_right + 1] > 0) / content_w
            if d >= INNER_LINE_EDGE_RATIO:
                return max(0, r - INNER_LINE_PADDING)
        return frame_line

    else:
        search_max = int(h * INNER_LINE_SEARCH_MAX_BOTTOM)
        scan_start = frame_line - INNER_LINE_GAP_MIN
        scan_end = max(0, frame_line - search_max)
        for r in range(scan_start, scan_end, -1):
            d = np.sum(edges[r, col_left:col_right + 1] > 0) / content_w
            if d >= INNER_LINE_EDGE_RATIO:
                return min(h - 1, r + INNER_LINE_PADDING)
        return frame_line
