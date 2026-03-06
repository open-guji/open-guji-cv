"""
古籍边框识别脚本。

读取 LSD 检测输出（JSON）和原图，识别：
1. 外边框（双层：外层粗、内层细）
2. 内部列间界栏

处理思路：
- 每条结构线独立拟合 slope / intercept（适应不均匀形变）
- 聚类基于共线性（点到拟合线的距离），不依赖全局 skew
- 先横后竖
- 默认双层边框（outer thick + inner thin）
- 支持中断/断续线段的合并

用法:
    PYTHONIOENCODING=utf-8 python border_detect.py [图片路径或文件夹]
    PYTHONIOENCODING=utf-8 python border_detect.py asset/06064237.cn_0003.jpg
    PYTHONIOENCODING=utf-8 python border_detect.py asset/
"""

import os
import sys
import json
import io
import argparse
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import cv2
import numpy as np


# ─── Helpers ─────────────────────────────────────────────────────


def _imread(image_path, flags=cv2.IMREAD_COLOR):
    """读取图片，支持 Windows 非 ASCII 路径。"""
    img = cv2.imread(image_path, flags)
    if img is None:
        buf = np.fromfile(image_path, dtype=np.uint8)
        img = cv2.imdecode(buf, flags)
    return img


def _imwrite(path, img):
    """写入图片，支持 Windows 非 ASCII 路径。"""
    ext = Path(path).suffix
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(path)


# ─── 线段合并 ────────────────────────────────────────────────────


def _merge_segments_1d(segments, max_gap):
    """合并一维线段列表，允许 max_gap 像素的中断。"""
    if not segments:
        return []
    segs = sorted(segments, key=lambda s: s[0])
    merged = [list(segs[0])]
    for s, e in segs[1:]:
        if s <= merged[-1][1] + max_gap:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [tuple(m) for m in merged]


def _total_coverage(segments):
    """计算线段总覆盖长度。"""
    return sum(e - s for s, e in segments)


# ─── 共线性聚类 ──────────────────────────────────────────────────


def _fit_line_from_endpoints(endpoints, weights=None):
    """对 [(coord1, pos1), (coord2, pos2), ...] 做加权线性回归。

    返回 (slope, intercept): pos = slope * coord + intercept
    """
    if len(endpoints) < 2:
        return 0.0, float(np.mean([p[1] for p in endpoints]))
    coords = np.array([p[0] for p in endpoints], dtype=np.float64)
    positions = np.array([p[1] for p in endpoints], dtype=np.float64)
    coord_range = coords.max() - coords.min()
    if coord_range < 5:
        return 0.0, float(np.mean(positions))
    if weights is not None:
        w = np.array(weights, dtype=np.float64)
    else:
        w = np.ones(len(coords))
    coeffs = np.polyfit(coords, positions, 1, w=w)
    return float(coeffs[0]), float(coeffs[1])


def _point_to_line_dist(coord, pos, slope, intercept):
    """点 (coord, pos) 到直线 pos = slope*coord + intercept 的垂直距离。"""
    return abs(pos - (slope * coord + intercept))


class _LineGroup:
    """一组共线的线段。维护增量拟合。"""

    def __init__(self):
        self.endpoints = []  # [(coord, pos)] — 每条线段贡献两个端点
        self.weights = []    # 每个端点的权重（线段长度的一半）
        self.seg_ranges = [] # [(seg_start, seg_end)] 沿主轴
        self.widths = []     # LSD width
        self.slope = 0.0
        self.intercept = 0.0

    def add(self, coord1, pos1, coord2, pos2, seg_s, seg_e, width):
        seg_len = seg_e - seg_s
        half_len = max(seg_len / 2, 1.0)
        self.endpoints.extend([(coord1, pos1), (coord2, pos2)])
        self.weights.extend([half_len, half_len])
        self.seg_ranges.append((seg_s, seg_e))
        self.widths.append(width)
        self._refit()

    def _refit(self):
        self.slope, self.intercept = _fit_line_from_endpoints(
            self.endpoints, self.weights)

    def dist_to(self, coord, pos):
        """点到当前拟合线的距离。"""
        return _point_to_line_dist(coord, pos, self.slope, self.intercept)

    def midpoint_dist(self, coord1, pos1, coord2, pos2):
        """线段中点到当前拟合线的距离。"""
        mc = (coord1 + coord2) / 2
        mp = (pos1 + pos2) / 2
        return self.dist_to(mc, mp)

    def endpoint_max_dist(self, coord1, pos1, coord2, pos2):
        """线段两端点到当前拟合线的最大距离。"""
        d1 = self.dist_to(coord1, pos1)
        d2 = self.dist_to(coord2, pos2)
        return max(d1, d2)


def cluster_lines(lines, axis, pos_tol, max_gap):
    """按共线性聚类线段，每组独立拟合参数化直线。

    对于水平线 axis='h': 主轴=x, 位置轴=y, 拟合 y = slope*x + intercept
    对于垂直线 axis='v': 主轴=y, 位置轴=x, 拟合 x = slope*y + intercept

    聚类规则：一条新线段的两端点到候选组拟合线的最大距离 <= pos_tol 则归入。

    Returns:
        clusters: [{
            "intercept": float,
            "slope": float,
            "segments": [(s, e)],  # 沿主轴的合并线段
            "total_length": float,
            "avg_width": float,
            "line_count": int,
        }, ...]
        按 intercept 排序。
    """
    if not lines:
        return []

    # 提取每条线段的端点信息
    # items: (mid_pos, coord1, pos1, coord2, pos2, seg_s, seg_e, width)
    # mid_pos 仅用于排序
    items = []
    for ln in lines:
        if axis == "h":
            c1, p1 = ln["x1"], ln["y1"]
            c2, p2 = ln["x2"], ln["y2"]
            seg_s = min(ln["x1"], ln["x2"])
            seg_e = max(ln["x1"], ln["x2"])
        else:
            c1, p1 = ln["y1"], ln["x1"]
            c2, p2 = ln["y2"], ln["x2"]
            seg_s = min(ln["y1"], ln["y2"])
            seg_e = max(ln["y1"], ln["y2"])
        mid_pos = (p1 + p2) / 2
        items.append((mid_pos, c1, p1, c2, p2, seg_s, seg_e, ln["width"]))

    # 按 mid_pos 排序，使贪心聚类倾向于先处理位置接近的线段
    items.sort(key=lambda x: x[0])

    groups = []  # [_LineGroup]
    for mid_pos, c1, p1, c2, p2, seg_s, seg_e, w in items:
        # 找最佳归属组（距离最小且在容差内）
        best_group = None
        best_dist = pos_tol + 1

        for g in groups:
            # 快速预筛：intercept 差太大的跳过
            if abs(mid_pos - g.intercept) > pos_tol * 3:
                # 但是 slope 大时 intercept 差距可以很大，用端点距离再判断
                d = g.endpoint_max_dist(c1, p1, c2, p2)
                if d > pos_tol:
                    continue
            else:
                d = g.endpoint_max_dist(c1, p1, c2, p2)
                if d > pos_tol:
                    continue

            if d < best_dist:
                best_dist = d
                best_group = g

        if best_group is not None:
            best_group.add(c1, p1, c2, p2, seg_s, seg_e, w)
        else:
            g = _LineGroup()
            g.add(c1, p1, c2, p2, seg_s, seg_e, w)
            groups.append(g)

    # ── 合并相近的组 ──
    # 初次贪心聚类可能因处理顺序把同一条物理线拆成多组，
    # 这里做一轮合并：如果两组的 intercept 差 < pos_tol 且 segment 有重叠/接近，合并。
    merged_groups = _merge_close_groups(groups, pos_tol, max_gap)

    # 构建结果
    clusters = []
    for g in merged_groups:
        merged = _merge_segments_1d(g.seg_ranges, max_gap)
        clusters.append({
            "intercept": g.intercept,
            "slope": g.slope,
            "segments": merged,
            "total_length": float(_total_coverage(merged)),
            "avg_width": float(np.mean(g.widths)),
            "line_count": len(g.seg_ranges),
        })

    clusters.sort(key=lambda c: c["intercept"])
    return clusters


def _merge_close_groups(groups, pos_tol, max_gap):
    """合并 intercept 相近的组。"""
    if len(groups) <= 1:
        return groups

    # 按 intercept 排序
    groups.sort(key=lambda g: g.intercept)
    merged = [groups[0]]
    for g in groups[1:]:
        last = merged[-1]
        # 判断是否应该合并：intercept 接近
        if abs(g.intercept - last.intercept) <= pos_tol:
            # 合并：把 g 的所有端点、段、宽度加入 last
            last.endpoints.extend(g.endpoints)
            last.weights.extend(g.weights)
            last.seg_ranges.extend(g.seg_ranges)
            last.widths.extend(g.widths)
            last._refit()
        else:
            merged.append(g)
    return merged


def _cluster_pos_at(cluster, coord):
    """计算聚类线在给定 coord 处的 position 值。"""
    return cluster["slope"] * coord + cluster["intercept"]


# ─── 结构线判定 ──────────────────────────────────────────────────


def _is_structural_line(c, frame_span, min_coverage_ratio):
    """判断 cluster 是否为结构线（边框或界栏），而非字符投影。

    通道1：传统覆盖率（总长度 / 跨度 >= min_coverage_ratio）
    通道2：高 merge_ratio（多条 LSD 线段合并为少数连续段）
        真正的边框线即使磨损，其 LSD 线段也会密集合并（merge_ratio 高），
        而字符笔画投影是零散独立的短段（merge_ratio 低）。
    """
    coverage = c["total_length"] / frame_span if frame_span > 0 else 0
    seg_count = len(c["segments"])
    merge_ratio = c["line_count"] / seg_count if seg_count > 0 else 0
    max_seg = max((e - s) for s, e in c["segments"]) if c["segments"] else 0

    # 通道1：传统覆盖率
    if coverage >= min_coverage_ratio:
        return True
    # 通道2：高 merge_ratio = 真正的独立直线（即使覆盖率低）
    if merge_ratio >= 5 and max_seg >= 100 and c["line_count"] >= 5:
        return True
    return False


# ─── 双层边框检测 ─────────────────────────────────────────────────


def _find_border_pair(clusters, side, frame_span, img_dim,
                      min_coverage_ratio=0.3, layer_max_dist=80,
                      edge_margin=10, slope_max_diff=0.02):
    """在一侧（min/max 方向）寻找双层边框。

    内层必须满足：与外层距离 <= layer_max_dist 且 slope 差 <= slope_max_diff。
    """
    candidates = [c for c in clusters
                  if _is_structural_line(c, frame_span, min_coverage_ratio)]

    if not candidates:
        return {"outer": None, "inner": None}

    def _is_edge_artifact(c):
        pos = c["intercept"]
        if pos < edge_margin or pos > img_dim - edge_margin:
            if c["avg_width"] < 2.0 or c["line_count"] <= 1:
                return True
        return False

    def _slope_compatible(outer_c, inner_c):
        """内层 slope 应与外层基本一致。"""
        return abs(inner_c["slope"] - outer_c["slope"]) <= slope_max_diff

    if side == "min":
        outer = None
        outer_idx = -1
        for i, c in enumerate(candidates):
            if _is_edge_artifact(c):
                continue
            outer = c
            outer_idx = i
            break

        if outer is None:
            return {"outer": None, "inner": None}

        inner = None
        for c in candidates[outer_idx + 1:]:
            dist = c["intercept"] - outer["intercept"]
            if dist > layer_max_dist:
                break
            if _is_edge_artifact(c):
                continue
            if not _slope_compatible(outer, c):
                continue
            inner = c
            break
    else:
        outer = None
        outer_idx = -1
        for i in range(len(candidates) - 1, -1, -1):
            c = candidates[i]
            if _is_edge_artifact(c):
                continue
            outer = c
            outer_idx = i
            break

        if outer is None:
            return {"outer": None, "inner": None}

        inner = None
        for i in range(outer_idx - 1, -1, -1):
            c = candidates[i]
            dist = outer["intercept"] - c["intercept"]
            if dist > layer_max_dist:
                break
            if _is_edge_artifact(c):
                continue
            if not _slope_compatible(outer, c):
                continue
            inner = c
            break

    return {"outer": outer, "inner": inner}


# ─── 缺失边框恢复 ────────────────────────────────────────────────


def _try_recover_faint_border(v_clusters, columns, column_dividers,
                               inner_left, inner_right,
                               inner_left_slope, inner_right_slope,
                               left_pair, right_pair,
                               img_width, inner_height, min_coverage_ratio,
                               expected_cols):
    """列数不足时，尝试在左/右空白区域恢复模糊的边框线。

    筒子页右页 → 右边可能有空白（需向右寻找边框）
    筒子页左页 → 左边可能有空白（需向左寻找边框）

    策略：
    1. 计算现有列的平均宽度
    2. 分别在左侧（0 ~ inner_left）和右侧（inner_right ~ img_width）
       搜索结构线候选
    3. 选择使新列宽度最接近平均宽度的候选
    4. 将原边框降级为列间界栏，用候选线作为新边框
    """
    if not columns:
        return None

    missing = expected_cols - len(columns)
    if missing <= 0:
        return None

    widths = [col["width"] for col in columns]
    mean_width = float(np.mean(widths))

    # 收集已用于边框的 intercept，避免重复
    border_intercepts = set()
    for pair in [left_pair, right_pair]:
        for key in ["outer", "inner"]:
            if pair[key] is not None:
                border_intercepts.add(pair[key]["intercept"])

    best_side = None  # "left" or "right"
    best_candidate = None
    best_width_diff = float("inf")

    # ── 右侧搜索：inner_right 到 img_width ──
    for vc in v_clusters:
        intercept = vc["intercept"]
        if intercept <= inner_right + 10:
            continue
        if intercept > img_width - 5:
            continue
        if intercept in border_intercepts:
            continue
        if not _is_structural_line(vc, inner_height, min_coverage_ratio):
            continue
        new_col_width = intercept - inner_right
        width_diff = abs(new_col_width - mean_width)
        if new_col_width < mean_width * 0.5 or new_col_width > mean_width * 1.5:
            continue
        if width_diff < best_width_diff:
            best_width_diff = width_diff
            best_candidate = vc
            best_side = "right"

    # ── 左侧搜索：0 到 inner_left ──
    for vc in v_clusters:
        intercept = vc["intercept"]
        if intercept >= inner_left - 10:
            continue
        if intercept < 5:
            continue
        if intercept in border_intercepts:
            continue
        if not _is_structural_line(vc, inner_height, min_coverage_ratio):
            continue
        new_col_width = inner_left - intercept
        width_diff = abs(new_col_width - mean_width)
        if new_col_width < mean_width * 0.5 or new_col_width > mean_width * 1.5:
            continue
        if width_diff < best_width_diff:
            best_width_diff = width_diff
            best_candidate = vc
            best_side = "left"

    # ── 备选策略：均宽推断 ──
    # 当没有结构线候选、但列宽高度一致时，用均宽推算边框位置
    if best_candidate is None:
        cv = float(np.std(widths) / mean_width) if mean_width > 0 else 1.0
        if cv >= 0.10:
            return None  # 列宽不够均匀，不适合推断

        # 尝试右侧推断
        pred_right = inner_right + mean_width
        # 尝试左侧推断
        pred_left = inner_left - mean_width

        right_ok = 10 < pred_right < img_width - 5
        left_ok = 5 < pred_left < img_width - 10

        if right_ok and left_ok:
            # 两侧都可能，选择空白更大的一侧
            right_margin = img_width - inner_right
            left_margin = inner_left
            if right_margin >= left_margin:
                best_side = "right"
            else:
                best_side = "left"
        elif right_ok:
            best_side = "right"
        elif left_ok:
            best_side = "left"
        else:
            return None

        if best_side == "right":
            new_intercept = pred_right
            print(f"  [恢复] 均宽推断右边框: x≈{new_intercept:.1f}, "
                  f"均宽={mean_width:.1f}, CV={cv:.3f}")
        else:
            new_intercept = pred_left
            print(f"  [恢复] 均宽推断左边框: x≈{new_intercept:.1f}, "
                  f"均宽={mean_width:.1f}, CV={cv:.3f}")

    else:
        seg_count = len(best_candidate["segments"])
        merge_ratio = (best_candidate["line_count"] / seg_count
                       if seg_count > 0 else 0)
        coverage = best_candidate["total_length"] / inner_height if inner_height > 0 else 0
        new_intercept = best_candidate["intercept"]
        best_side = best_side  # already set

    if best_side == "right":
        new_col_width = new_intercept - inner_right
        if best_candidate is not None:
            print(f"  [恢复] 在右侧找到模糊边框: x≈{new_intercept:.1f}, "
                  f"coverage={coverage:.1%}, merge_ratio={merge_ratio:.1f}, "
                  f"新列宽={new_col_width:.1f} (均宽={mean_width:.1f})")

        # 原来的右边框降级为列间界栏
        old_right_cluster = right_pair.get("inner") or right_pair.get("outer")
        if old_right_cluster is not None:
            old_coverage = old_right_cluster["total_length"] / inner_height
            max_seg_len = (max((e - s) for s, e in old_right_cluster["segments"])
                          if old_right_cluster["segments"] else 0)
            column_dividers.append({
                **old_right_cluster,
                "coverage": float(old_coverage),
                "max_seg_len": float(max_seg_len),
                "max_seg_coverage": float(max_seg_len / inner_height) if inner_height > 0 else 0,
            })
            column_dividers.sort(key=lambda cd: cd["intercept"])

        # 更新右边框
        right_pair = {"outer": best_candidate, "inner": None}
        inner_right = new_intercept
        inner_right_slope = (best_candidate["slope"] if best_candidate is not None
                             else inner_right_slope)

    else:  # left
        new_col_width = inner_left - new_intercept
        if best_candidate is not None:
            print(f"  [恢复] 在左侧找到模糊边框: x≈{new_intercept:.1f}, "
                  f"coverage={coverage:.1%}, merge_ratio={merge_ratio:.1f}, "
                  f"新列宽={new_col_width:.1f} (均宽={mean_width:.1f})")

        # 原来的左边框降级为列间界栏
        old_left_cluster = left_pair.get("inner") or left_pair.get("outer")
        if old_left_cluster is not None:
            old_coverage = old_left_cluster["total_length"] / inner_height
            max_seg_len = (max((e - s) for s, e in old_left_cluster["segments"])
                          if old_left_cluster["segments"] else 0)
            column_dividers.append({
                **old_left_cluster,
                "coverage": float(old_coverage),
                "max_seg_len": float(max_seg_len),
                "max_seg_coverage": float(max_seg_len / inner_height) if inner_height > 0 else 0,
            })
            column_dividers.sort(key=lambda cd: cd["intercept"])

        # 更新左边框
        left_pair = {"outer": best_candidate, "inner": None}
        inner_left = new_intercept
        inner_left_slope = (best_candidate["slope"] if best_candidate is not None
                            else inner_left_slope)

    # 重建列区域
    div_intercepts = sorted([inner_left] +
                            [cd["intercept"] for cd in column_dividers] +
                            [inner_right])
    columns = []
    for i in range(len(div_intercepts) - 1):
        lx = div_intercepts[i]
        rx = div_intercepts[i + 1]
        columns.append({
            "index": i,
            "left_x": float(lx),
            "right_x": float(rx),
            "width": float(rx - lx),
        })

    return (inner_left, inner_right, inner_left_slope, inner_right_slope,
            left_pair, right_pair, column_dividers, columns)


# ─── 主检测逻辑 ──────────────────────────────────────────────────


def detect_borders(lsd_data, img_width, img_height,
                   pos_tol=15, max_gap=60, min_coverage_ratio=0.3,
                   layer_max_dist=80, expected_cols=None):
    """从 LSD 数据中识别边框结构。"""
    all_lines = lsd_data["lines"]
    h_lines = [ln for ln in all_lines if ln["type"] == "horizontal"]
    v_lines = [ln for ln in all_lines if ln["type"] == "vertical"]

    print(f"  水平线段: {len(h_lines)} 条")
    print(f"  垂直线段: {len(v_lines)} 条")

    # ── 第一步：共线性聚类 ──
    h_clusters = cluster_lines(h_lines, "h", pos_tol, max_gap)
    v_clusters = cluster_lines(v_lines, "v", pos_tol, max_gap)

    print(f"  水平线聚类: {len(h_clusters)} 组")
    print(f"  垂直线聚类: {len(v_clusters)} 组")

    # ── 第二步：识别外边框（先横后竖） ──
    h_span = img_width
    v_span = img_height

    print(f"\n  --- 水平边框检测 ---")
    top_pair = _find_border_pair(h_clusters, "min", h_span, img_height,
                                 min_coverage_ratio, layer_max_dist)
    bottom_pair = _find_border_pair(h_clusters, "max", h_span, img_height,
                                    min_coverage_ratio, layer_max_dist)

    _print_pair("上边框", top_pair)
    _print_pair("下边框", bottom_pair)

    frame_top = _get_outer_intercept(top_pair, 0)
    frame_bottom = _get_outer_intercept(bottom_pair, img_height)

    print(f"\n  --- 垂直边框检测 ---")
    left_pair = _find_border_pair(v_clusters, "min", v_span, img_width,
                                  min_coverage_ratio, layer_max_dist)
    right_pair = _find_border_pair(v_clusters, "max", v_span, img_width,
                                   min_coverage_ratio, layer_max_dist)

    _print_pair("左边框", left_pair)
    _print_pair("右边框", right_pair)

    frame_left = _get_outer_intercept(left_pair, 0)
    frame_right = _get_outer_intercept(right_pair, img_width)

    inner_top = _get_inner_intercept(top_pair, frame_top)
    inner_bottom = _get_inner_intercept(bottom_pair, frame_bottom)
    inner_left = _get_inner_intercept(left_pair, frame_left)
    inner_right = _get_inner_intercept(right_pair, frame_right)

    inner_top_slope = _get_inner_slope(top_pair, 0.0)
    inner_bottom_slope = _get_inner_slope(bottom_pair, 0.0)
    inner_left_slope = _get_inner_slope(left_pair, 0.0)
    inner_right_slope = _get_inner_slope(right_pair, 0.0)

    # ── Sanity check: 上下边框不应重叠 ──
    if inner_bottom - inner_top < img_height * 0.3:
        print(f"  [WARN] 上下边框异常: top={inner_top:.1f}, bottom={inner_bottom:.1f}, "
              f"差={inner_bottom - inner_top:.1f} < {img_height * 0.3:.1f}")
        _top_cand = [c for c in h_clusters
                     if c["intercept"] < img_height * 0.15
                     and c["total_length"] >= h_span * 0.05]
        _bot_cand = [c for c in h_clusters
                     if c["intercept"] > img_height * 0.85
                     and c["total_length"] >= h_span * 0.05]

        if _top_cand:
            best_top = max(_top_cand, key=lambda c: c["total_length"])
            inner_top = best_top["intercept"]
            inner_top_slope = best_top["slope"]
            if top_pair["outer"] is None or top_pair["outer"]["intercept"] > img_height * 0.5:
                top_pair = {"outer": best_top, "inner": None}
                frame_top = best_top["intercept"]

        if _bot_cand:
            best_bot = max(_bot_cand, key=lambda c: c["total_length"])
            inner_bottom = best_bot["intercept"]
            inner_bottom_slope = best_bot["slope"]
            if bottom_pair["outer"] is None or bottom_pair["outer"]["intercept"] < img_height * 0.5:
                bottom_pair = {"outer": best_bot, "inner": None}
                frame_bottom = best_bot["intercept"]

        # ── 仍未修正：用竖线段端点推断上下边框 ──
        if inner_bottom - inner_top < img_height * 0.3 and v_clusters:
            print(f"  [WARN] 水平线修正失败，从竖线端点推断上下边框")
            # 收集所有足够长的竖线段的 y 范围
            v_y_mins = []
            v_y_maxs = []
            for vc in v_clusters:
                if vc["total_length"] < img_height * 0.3:
                    continue
                for seg_start, seg_end in vc["segments"]:
                    v_y_mins.append(seg_start)
                    v_y_maxs.append(seg_end)
            if v_y_mins and v_y_maxs:
                inferred_top = float(np.median(v_y_mins))
                inferred_bot = float(np.median(v_y_maxs))
                if inferred_bot - inferred_top > img_height * 0.3:
                    inner_top = inferred_top
                    inner_bottom = inferred_bot
                    inner_top_slope = 0.0
                    inner_bottom_slope = 0.0
                    frame_top = inferred_top
                    frame_bottom = inferred_bot
                    top_pair = {"outer": None, "inner": None}
                    bottom_pair = {"outer": None, "inner": None}

        print(f"  [WARN] 修正后: top={inner_top:.1f}, bottom={inner_bottom:.1f}")

    # ── 第三步：识别内部列间界栏 ──
    print(f"\n  --- 列间界栏检测 ---")
    border_intercepts = set()
    for pair in [left_pair, right_pair]:
        for key in ["outer", "inner"]:
            if pair[key] is not None:
                border_intercepts.add(pair[key]["intercept"])

    inner_height = inner_bottom - inner_top
    if inner_height <= 0:
        inner_height = v_span

    column_dividers = []
    for vc in v_clusters:
        intercept = vc["intercept"]
        if intercept in border_intercepts:
            continue
        if intercept < inner_left - pos_tol or intercept > inner_right + pos_tol:
            continue
        # 排除图片边缘伪线
        if intercept < 10 or intercept > img_width - 10:
            continue
        coverage = vc["total_length"] / inner_height
        max_seg_len = max((e - s) for s, e in vc["segments"]) if vc["segments"] else 0
        max_seg_coverage = max_seg_len / inner_height
        # 用 merge_ratio 判断是否为独立直线（磨损界栏也能通过）
        seg_count = len(vc["segments"])
        merge_ratio = vc["line_count"] / seg_count if seg_count > 0 else 0
        is_structural = merge_ratio >= 5 and vc["line_count"] >= 5
        if not is_structural:
            if coverage < 0.30 and max_seg_coverage < 0.20:
                continue
            if max_seg_coverage < 0.10:
                continue
        # 界栏的 slope 不应太大（> ~2° 就很可疑）
        if abs(vc["slope"]) > 0.04:
            continue
        column_dividers.append({
            **vc,
            "coverage": float(coverage),
            "max_seg_len": float(max_seg_len),
            "max_seg_coverage": float(max_seg_coverage),
        })

    print(f"  列间界栏: {len(column_dividers)} 条")
    for cd in column_dividers:
        gap_info = _describe_segments(cd["segments"])
        print(f"    x≈{cd['intercept']:.1f}, slope={cd['slope']:.4f}, "
              f"宽={cd['avg_width']:.1f}, "
              f"覆盖={cd['coverage']:.1%}, "
              f"最长段={cd['max_seg_coverage']:.1%}, "
              f"段数={len(cd['segments'])}{gap_info}")

    # ── 第四步：构建列区域 ──
    div_intercepts = sorted([inner_left] +
                            [cd["intercept"] for cd in column_dividers] +
                            [inner_right])

    columns = []
    for i in range(len(div_intercepts) - 1):
        lx = div_intercepts[i]
        rx = div_intercepts[i + 1]
        columns.append({
            "index": i,
            "left_x": float(lx),
            "right_x": float(rx),
            "width": float(rx - lx),
        })

    print(f"\n  版面共 {len(columns)} 列")

    # ── 第 4.5 步：过滤因伪界栏产生的窄列 ──
    # 如果某列宽度远小于中位列宽，说明是一条伪界栏把正常列劈成了
    # 一个极窄列和一个稍窄列。移除对应界栏即可恢复。
    if len(columns) >= 3:
        widths = [col["width"] for col in columns]
        median_w = float(np.median(widths))
        narrow_threshold = median_w * 0.3  # 低于中位宽 30% 即为异常窄
        narrow_cols = [col for col in columns if col["width"] < narrow_threshold]
        if narrow_cols:
            # 窄列是由一条伪界栏紧贴真界栏/边框产生的。
            # 只移除窄列两侧中**较弱**的那条界栏。
            div_map = {cd["intercept"]: cd for cd in column_dividers}
            remove_dividers = set()
            for nc in narrow_cols:
                left_cd = div_map.get(nc["left_x"])
                right_cd = div_map.get(nc["right_x"])
                if left_cd and right_cd:
                    # 两侧都是界栏：移除覆盖率较低的那条
                    left_cov = left_cd.get("coverage", left_cd["total_length"])
                    right_cov = right_cd.get("coverage", right_cd["total_length"])
                    if left_cov <= right_cov:
                        remove_dividers.add(nc["left_x"])
                    else:
                        remove_dividers.add(nc["right_x"])
                elif left_cd:
                    remove_dividers.add(nc["left_x"])
                elif right_cd:
                    remove_dividers.add(nc["right_x"])
                # 两侧都不是界栏（即都是边框），不处理
            if remove_dividers:
                removed_count = len(remove_dividers)
                column_dividers = [cd for cd in column_dividers
                                   if cd["intercept"] not in remove_dividers]
                # 重新构建列
                div_intercepts = sorted(
                    [inner_left] +
                    [cd["intercept"] for cd in column_dividers] +
                    [inner_right])
                columns = []
                for i in range(len(div_intercepts) - 1):
                    lx = div_intercepts[i]
                    rx = div_intercepts[i + 1]
                    columns.append({
                        "index": i,
                        "left_x": float(lx),
                        "right_x": float(rx),
                        "width": float(rx - lx),
                    })
                print(f"  [窄列过滤] 移除 {removed_count} 条伪界栏 "
                      f"(threshold={narrow_threshold:.0f}px)，"
                      f"修正为 {len(columns)} 列")

    # ── 第五步：列数不足时尝试恢复缺失边框 ──
    if expected_cols is not None and len(columns) < expected_cols:
        recovered = _try_recover_faint_border(
            v_clusters, columns, column_dividers,
            inner_left, inner_right, inner_left_slope, inner_right_slope,
            left_pair, right_pair,
            img_width, inner_height, min_coverage_ratio,
            expected_cols)
        if recovered is not None:
            (inner_left, inner_right, inner_left_slope, inner_right_slope,
             left_pair, right_pair, column_dividers, columns) = recovered
            print(f"  [恢复] 修正后版面共 {len(columns)} 列")

    # ── 组装结果 ──
    result = {
        "image_size": {"width": img_width, "height": img_height},
        "outer_frame": {
            "top": _format_pair(top_pair),
            "bottom": _format_pair(bottom_pair),
            "left": _format_pair(left_pair),
            "right": _format_pair(right_pair),
        },
        "inner_frame": {
            "top": {"intercept": float(inner_top), "slope": float(inner_top_slope)},
            "bottom": {"intercept": float(inner_bottom), "slope": float(inner_bottom_slope)},
            "left": {"intercept": float(inner_left), "slope": float(inner_left_slope)},
            "right": {"intercept": float(inner_right), "slope": float(inner_right_slope)},
        },
        "column_dividers": [
            {
                "intercept": cd["intercept"],
                "slope": cd["slope"],
                "avg_width": cd["avg_width"],
                "coverage": cd["coverage"],
                "segments": [{"start": s, "end": e} for s, e in cd["segments"]],
                "line_count": cd["line_count"],
            }
            for cd in column_dividers
        ],
        "num_columns": len(columns),
        "columns": columns,
        "debug": {
            "h_clusters_count": len(h_clusters),
            "v_clusters_count": len(v_clusters),
            "h_clusters": [
                {"intercept": c["intercept"], "slope": c["slope"],
                 "total_length": c["total_length"],
                 "avg_width": c["avg_width"], "line_count": c["line_count"],
                 "seg_count": len(c["segments"])}
                for c in h_clusters
            ],
            "v_clusters": [
                {"intercept": c["intercept"], "slope": c["slope"],
                 "total_length": c["total_length"],
                 "avg_width": c["avg_width"], "line_count": c["line_count"],
                 "seg_count": len(c["segments"])}
                for c in v_clusters
            ],
        },
    }

    return result


# ─── 辅助函数 ─────────────────────────────────────────────────────


def _get_outer_intercept(pair, default):
    if pair["outer"] is not None:
        return pair["outer"]["intercept"]
    return default


def _get_inner_intercept(pair, fallback):
    if pair["inner"] is not None:
        return pair["inner"]["intercept"]
    return fallback


def _get_inner_slope(pair, fallback):
    if pair["inner"] is not None:
        return pair["inner"]["slope"]
    if pair["outer"] is not None:
        return pair["outer"]["slope"]
    return fallback


def _print_pair(name, pair):
    outer = pair["outer"]
    inner = pair["inner"]
    if outer is None:
        print(f"  {name}: 未检测到")
        return
    gap_info = _describe_segments(outer["segments"])
    print(f"  {name} 外层: pos≈{outer['intercept']:.1f}, "
          f"slope={outer['slope']:.4f}, "
          f"宽={outer['avg_width']:.1f}, "
          f"长={outer['total_length']:.0f}, "
          f"段数={len(outer['segments'])}{gap_info}")
    if inner is not None:
        dist = abs(inner["intercept"] - outer["intercept"])
        gap_info = _describe_segments(inner["segments"])
        print(f"  {name} 内层: pos≈{inner['intercept']:.1f}, "
              f"slope={inner['slope']:.4f}, "
              f"宽={inner['avg_width']:.1f}, "
              f"长={inner['total_length']:.0f}, "
              f"段数={len(inner['segments'])}, "
              f"层距={dist:.1f}{gap_info}")
    else:
        print(f"  {name} 内层: 未检测到（单层边框）")


def _describe_segments(segments):
    if len(segments) <= 1:
        return ""
    gaps = []
    for i in range(len(segments) - 1):
        gap = segments[i + 1][0] - segments[i][1]
        gaps.append(gap)
    return f", 中断{len(gaps)}处(gap={','.join(f'{g:.0f}' for g in gaps)})"


def _format_pair(pair):
    def fmt_layer(cluster):
        if cluster is None:
            return None
        return {
            "intercept": cluster["intercept"],
            "slope": cluster["slope"],
            "avg_width": cluster["avg_width"],
            "total_length": cluster["total_length"],
            "line_count": cluster["line_count"],
            "segments": [{"start": s, "end": e} for s, e in cluster["segments"]],
        }
    return {
        "outer": fmt_layer(pair["outer"]),
        "inner": fmt_layer(pair["inner"]),
    }


# ─── 可视化 ──────────────────────────────────────────────────────


COLOR_OUTER = (0, 0, 220)       # 红色
COLOR_INNER = (0, 140, 255)     # 橙色
COLOR_DIVIDER = (0, 200, 0)     # 绿色


def _draw_parametric_seg(img, slope, intercept, seg_start, seg_end,
                         axis, color, thickness):
    """绘制参数化线段。

    axis='h': y = slope*x + intercept, x 从 seg_start 到 seg_end
    axis='v': x = slope*y + intercept, y 从 seg_start 到 seg_end
    """
    if axis == "h":
        x1 = int(seg_start)
        y1 = int(slope * seg_start + intercept)
        x2 = int(seg_end)
        y2 = int(slope * seg_end + intercept)
    else:
        y1 = int(seg_start)
        x1 = int(slope * seg_start + intercept)
        y2 = int(seg_end)
        x2 = int(slope * seg_end + intercept)
    cv2.line(img, (x1, y1), (x2, y2), color, thickness)


def draw_borders(image_path, result, output_path):
    """将边框检测结果绘制到原图上。"""
    img = _imread(image_path)
    if img is None:
        print(f"  无法读取图片: {image_path}")
        return

    overlay = img.copy()
    frame = result["outer_frame"]
    inner = result["inner_frame"]

    # 绘制列填充（半透明）
    col_overlay = img.copy()
    il = inner["left"]
    ir = inner["right"]
    it = inner["top"]
    ib = inner["bottom"]
    for i, col in enumerate(result["columns"]):
        color = (255, 245, 230) if i % 2 == 0 else (230, 245, 255)
        lx_int = col["left_x"]
        rx_int = col["right_x"]
        # 用各列自己的界栏 slope（如果有），否则用内框的
        v_slope = il["slope"]
        # 四角
        y_tl = int(it["slope"] * lx_int + it["intercept"])
        y_tr = int(it["slope"] * rx_int + it["intercept"])
        y_bl = int(ib["slope"] * lx_int + ib["intercept"])
        y_br = int(ib["slope"] * rx_int + ib["intercept"])
        x_tl = int(v_slope * y_tl + lx_int)
        x_bl = int(v_slope * y_bl + lx_int)
        x_tr = int(v_slope * y_tr + rx_int)
        x_br = int(v_slope * y_br + rx_int)
        pts = np.array([[x_tl, y_tl], [x_tr, y_tr],
                         [x_br, y_br], [x_bl, y_bl]], dtype=np.int32)
        cv2.fillPoly(col_overlay, [pts], color)
    overlay = cv2.addWeighted(col_overlay, 0.3, overlay, 0.7, 0)

    # 绘制外边框
    for side_name, side_data in frame.items():
        is_h = side_name in ("top", "bottom")
        axis = "h" if is_h else "v"
        for layer_name, layer_data in side_data.items():
            if layer_data is None:
                continue
            color = COLOR_OUTER if layer_name == "outer" else COLOR_INNER
            thickness = 3 if layer_name == "outer" else 2
            for seg in layer_data["segments"]:
                _draw_parametric_seg(overlay, layer_data["slope"],
                                     layer_data["intercept"],
                                     seg["start"], seg["end"],
                                     axis, color, thickness)

    # 绘制列间界栏
    for cd in result["column_dividers"]:
        for seg in cd["segments"]:
            _draw_parametric_seg(overlay, cd["slope"], cd["intercept"],
                                 seg["start"], seg["end"],
                                 "v", COLOR_DIVIDER, 2)

    # 列编号
    for col in result["columns"]:
        cx = int((col["left_x"] + col["right_x"]) / 2)
        cy = int(it["slope"] * cx + it["intercept"]) - 10
        if cy < 20:
            cy = int(ib["slope"] * cx + ib["intercept"]) + 20
        label = f"Col{col['index']}"
        cv2.putText(overlay, label, (cx - 15, cy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)

    # 图例
    lx, ly = 10, 25
    for label, color in [("Outer border", COLOR_OUTER),
                          ("Inner border", COLOR_INNER),
                          ("Column divider", COLOR_DIVIDER)]:
        cv2.line(overlay, (lx, ly), (lx + 30, ly), color, 2)
        cv2.putText(overlay, label, (lx + 35, ly + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
        ly += 22

    # 内框虚线
    _draw_dashed_inner_frame(overlay, inner, (180, 180, 0), thickness=1, dash=15)

    _imwrite(output_path, overlay)
    print(f"  已保存标注图: {output_path}")


def _draw_dashed_inner_frame(img, inner, color, thickness=1, dash=10):
    it = inner["top"]
    ib = inner["bottom"]
    il = inner["left"]
    ir = inner["right"]
    tl = _intersect_hv(it["slope"], it["intercept"], il["slope"], il["intercept"])
    tr = _intersect_hv(it["slope"], it["intercept"], ir["slope"], ir["intercept"])
    bl = _intersect_hv(ib["slope"], ib["intercept"], il["slope"], il["intercept"])
    br = _intersect_hv(ib["slope"], ib["intercept"], ir["slope"], ir["intercept"])
    for p1, p2 in [(tl, tr), (bl, br), (tl, bl), (tr, br)]:
        _draw_dashed_line(img, p1, p2, color, thickness, dash)


def _intersect_hv(h_slope, h_intercept, v_slope, v_intercept):
    """水平线 y=h_slope*x+h_intercept 与 垂直线 x=v_slope*y+v_intercept 的交点。"""
    denom = 1.0 - h_slope * v_slope
    if abs(denom) < 1e-10:
        return (int(v_intercept), int(h_intercept))
    y = (h_slope * v_intercept + h_intercept) / denom
    x = v_slope * y + v_intercept
    return (int(x), int(y))


def _draw_dashed_line(img, pt1, pt2, color, thickness, dash):
    x1, y1 = pt1
    x2, y2 = pt2
    dx = x2 - x1
    dy = y2 - y1
    length = np.sqrt(dx * dx + dy * dy)
    if length == 0:
        return
    steps = max(int(length / dash), 1)
    for i in range(0, steps, 2):
        sx = int(x1 + dx * i / steps)
        sy = int(y1 + dy * i / steps)
        ex = int(x1 + dx * min(i + 1, steps) / steps)
        ey = int(y1 + dy * min(i + 1, steps) / steps)
        cv2.line(img, (sx, sy), (ex, ey), color, thickness)


# ─── 主程序 ──────────────────────────────────────────────────────


def find_lsd_json(image_path, lsd_dir="output/lsd"):
    stem = Path(image_path).stem
    lsd_json = Path(lsd_dir) / f"{stem}_lsd.json"
    if lsd_json.exists():
        return str(lsd_json)
    return None


def process_image(image_path, lsd_dir="output/lsd",
                  pos_tol=15, max_gap=60,
                  min_coverage_ratio=0.3, layer_max_dist=80):
    lsd_json_path = find_lsd_json(image_path, lsd_dir)
    if lsd_json_path is None:
        print(f"  未找到 LSD 数据，请先运行 lsd_detect.py")
        return None

    print(f"  LSD 数据: {lsd_json_path}")

    with open(lsd_json_path, "r", encoding="utf-8") as f:
        lsd_data = json.load(f)

    img_w = lsd_data["image_size"]["width"]
    img_h = lsd_data["image_size"]["height"]

    result = detect_borders(lsd_data, img_w, img_h,
                            pos_tol=pos_tol, max_gap=max_gap,
                            min_coverage_ratio=min_coverage_ratio,
                            layer_max_dist=layer_max_dist)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="古籍边框识别 — 基于 LSD 线段检测结果")
    parser.add_argument("path", nargs="?", default=None,
                        help="图片文件或文件夹路径（默认: asset/）")
    parser.add_argument("--lsd-dir", default="output/lsd",
                        help="LSD 输出目录（默认: output/lsd）")
    parser.add_argument("-o", "--output", default="output/borders",
                        help="输出文件夹（默认: output/borders）")
    parser.add_argument("--pos-tol", type=float, default=15,
                        help="位置聚类容差，像素（默认: 15）")
    parser.add_argument("--max-gap", type=float, default=60,
                        help="断续线段合并最大间隙，像素（默认: 60）")
    parser.add_argument("--min-coverage", type=float, default=0.3,
                        help="边框线最小覆盖比（默认: 0.3）")
    parser.add_argument("--layer-max-dist", type=float, default=80,
                        help="双层边框层间最大距离，像素（默认: 80）")
    args = parser.parse_args()

    exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
    skip_suffixes = {"_lsd", "_borders", "_annotated"}

    if args.path:
        target = Path(args.path)
        if target.is_file():
            files = [str(target)]
        elif target.is_dir():
            files = sorted(
                str(f) for f in target.iterdir()
                if f.suffix.lower() in exts
                and not any(f.stem.endswith(s) for s in skip_suffixes))
        else:
            print(f"路径不存在: {target}")
            sys.exit(1)
    else:
        folder = Path(__file__).parent / "asset"
        files = sorted(
            str(f) for f in folder.iterdir()
            if f.suffix.lower() in exts
            and not any(f.stem.endswith(s) for s in skip_suffixes))

    if not files:
        print("未找到图片。")
        sys.exit(1)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"找到 {len(files)} 张图片。")
    print(f"LSD 数据目录: {args.lsd_dir}")
    print(f"输出目录: {out_dir}\n")

    for image_path in files:
        base = Path(image_path).stem
        print(f"{'=' * 60}")
        print(f"处理: {os.path.basename(image_path)}")
        print(f"{'=' * 60}")

        result = process_image(
            image_path, lsd_dir=args.lsd_dir,
            pos_tol=args.pos_tol, max_gap=args.max_gap,
            min_coverage_ratio=args.min_coverage,
            layer_max_dist=args.layer_max_dist)

        if result is None:
            print()
            continue

        of = result["outer_frame"]
        print(f"\n  === 检测摘要 ===")
        for side in ["top", "bottom", "left", "right"]:
            outer = of[side]["outer"]
            inner = of[side]["inner"]
            o_str = (f"pos≈{outer['intercept']:.0f}, "
                     f"slope={outer['slope']:.4f}, "
                     f"w={outer['avg_width']:.1f}") if outer else "无"
            i_str = (f"pos≈{inner['intercept']:.0f}, "
                     f"slope={inner['slope']:.4f}, "
                     f"w={inner['avg_width']:.1f}") if inner else "无"
            print(f"  {side:>6}: 外层[{o_str}] 内层[{i_str}]")
        print(f"  列数: {result['num_columns']}")
        print(f"  界栏: {len(result['column_dividers'])} 条")

        out_img = out_dir / f"{base}_borders.jpg"
        draw_borders(image_path, result, str(out_img))

        out_json = out_dir / f"{base}_borders.json"
        output_data = {k: v for k, v in result.items() if k != "debug"}
        with open(str(out_json), "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        print(f"  已保存 JSON: {out_json}")

        debug_json = out_dir / f"{base}_borders_debug.json"
        with open(str(debug_json), "w", encoding="utf-8") as f:
            json.dump(result["debug"], f, ensure_ascii=False, indent=2)
        print(f"  已保存调试: {debug_json}")
        print()


if __name__ == "__main__":
    main()
