"""网格匹配算法原型 — 在古籍半页图上检测 N 列等距网格并透视校正提取。

用法:
    cd d:/workspace/open-guji-cv
    python scripts/test_grid_match.py output/hanshu_yiwenzhi/s2_split/page_024_right.png --cols 10
    python scripts/test_grid_match.py data/hanshu_yiwenzhi/page_024.png --cols 10 --spread

算法:
    1. LSD 检测垂直/水平线段 → 共线性聚类
    2. 从垂直线簇中选出 N+1 条最优等距竖线（左右边框 + N-1 界栏）
    3. 检测上下水平边框
    4. 用网格交点 → 理想网格点 拟合 Homography
    5. 透视变换提取校正后的内容
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# 复用项目已有的线段聚类
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))
from border_detect import cluster_lines, _find_border_pair


# ──────────────────────────────────────────────────────────────────
# LSD 检测
# ──────────────────────────────────────────────────────────────────

MIN_LINE_LENGTH = 30
ANGLE_TOL = 10.0  # 度


def detect_lines(gray: np.ndarray) -> list[dict]:
    """LSD 检测线段并分类为水平/垂直。"""
    lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    raw_lines, widths, _, _ = lsd.detect(gray)
    if raw_lines is None:
        return []

    result = []
    for i, line in enumerate(raw_lines):
        x1, y1, x2, y2 = line[0]
        dx, dy = x2 - x1, y2 - y1
        length = np.sqrt(dx * dx + dy * dy)
        if length < MIN_LINE_LENGTH:
            continue

        width = float(widths[i][0]) if widths is not None else 1.0
        angle_from_vert = abs(np.degrees(np.arctan2(abs(dx), abs(dy))))

        if angle_from_vert <= ANGLE_TOL:
            line_type = "vertical"
        elif angle_from_vert >= (90 - ANGLE_TOL):
            line_type = "horizontal"
        else:
            continue

        result.append({
            "x1": float(x1), "y1": float(y1),
            "x2": float(x2), "y2": float(y2),
            "length": float(length),
            "width": width,
            "type": line_type,
        })
    return result


# ──────────────────────────────────────────────────────────────────
# 从聚类中选出等距竖线
# ──────────────────────────────────────────────────────────────────

def _has_companion(intercept: float, clusters: list[dict],
                    direction: str, max_dist: float = 80,
                    min_length: float = 0) -> bool:
    """检查某条线在指定方向上是否有伴随结构线（双层边框的外层）。

    只考虑长度 >= min_length 的线，避免文字笔画噪声。
    """
    for c in clusters:
        if c["total_length"] < min_length:
            continue
        pos = c["intercept"]
        if direction == "left" and 5 < intercept - pos <= max_dist:
            return True
        if direction == "right" and 5 < pos - intercept <= max_dist:
            return True
    return False


def select_grid_verticals(
    v_clusters: list[dict],
    num_cols: int,
    img_width: int,
    img_height: int,
    min_length_ratio: float = 0.3,
) -> list[dict] | None:
    """从垂直线簇中选出 num_cols+1 条最优等距竖线。

    评分综合考虑：等距偏差 + 线条长度一致性 + 双层边框结构。
    """
    # 过滤：至少覆盖图高的 min_length_ratio
    min_len = img_height * min_length_ratio
    candidates = [c for c in v_clusters if c["total_length"] >= min_len]

    if len(candidates) < num_cols + 1:
        print(f"  竖线不足: 需要 {num_cols + 1}, 找到 {len(candidates)} "
              f"(过滤前 {len(v_clusters)})")
        return None

    candidates.sort(key=lambda c: c["intercept"])

    # 伴随线最小长度：候选线中位数长度的 50%（排除笔画噪声）
    _companion_min_len = float(np.median([c["total_length"] for c in candidates])) * 0.5

    best_score = float("inf")
    best_group = None
    n_needed = num_cols + 1
    intercepts = np.array([c["intercept"] for c in candidates])

    for i_left in range(len(candidates) - n_needed + 1):
        left_pos = intercepts[i_left]
        for i_right in range(i_left + n_needed - 1, len(candidates)):
            right_pos = intercepts[i_right]
            span = right_pos - left_pos
            if span < img_width * 0.3:
                continue

            ideal_spacing = span / num_cols
            group = [i_left]
            total_dev = 0.0
            failed = False
            search_start = i_left + 1

            for k in range(1, num_cols):
                ideal_pos = left_pos + k * ideal_spacing
                best_idx = -1
                best_dist = float("inf")
                for j in range(search_start, i_right):
                    d = abs(intercepts[j] - ideal_pos)
                    if d < best_dist:
                        best_dist = d
                        best_idx = j

                if best_idx == -1 or best_dist > ideal_spacing * 0.3:
                    failed = True
                    break
                group.append(best_idx)
                total_dev += best_dist
                search_start = best_idx + 1

            if failed:
                continue
            group.append(i_right)

            # ── 评分 ──
            norm_dev = total_dev / (num_cols * ideal_spacing) if ideal_spacing > 0 else float("inf")

            # 长度一致性
            lengths = [candidates[idx]["total_length"] for idx in group]
            med_len = float(np.median(lengths))
            length_cv = float(np.std(lengths) / med_len) if med_len > 0 else 0.0

            # 双层边框奖励：真正的边框（内层）外侧应有一条很近的
            # 伴随线（外层，距离 < 间距的一半），界栏线间距则约等于 ideal_spacing
            companion_max = min(80, ideal_spacing * 0.5)
            border_bonus = 0.0
            has_close_left = _has_companion(left_pos, v_clusters, "left", max_dist=companion_max, min_length=_companion_min_len)
            if has_close_left:
                border_bonus += 0.15
            has_close_right = _has_companion(right_pos, v_clusters, "right", max_dist=companion_max, min_length=_companion_min_len)
            if has_close_right:
                border_bonus += 0.15

            # 边缘惩罚：边框越靠近图片边缘越可能包含版心/中缝
            # 使用连续惩罚：在图片 10% 以内线性增加
            edge_zone = img_width * 0.15
            edge_penalty = 0.0
            if left_pos < edge_zone:
                edge_penalty += 0.3 * (1.0 - left_pos / edge_zone)
            if right_pos > img_width - edge_zone:
                edge_penalty += 0.3 * (1.0 - (img_width - right_pos) / edge_zone)

            score = norm_dev + length_cv * 1.0 - border_bonus + edge_penalty
            if score < best_score:
                best_score = score
                best_group = group
                _best_dev = norm_dev
                _best_span = span
                _best_lcv = length_cv
                _best_border = border_bonus

    if best_group is None:
        print("  无法找到等距竖线组合")
        return None

    result = [candidates[i] for i in best_group]
    spacing = (result[-1]["intercept"] - result[0]["intercept"]) / num_cols

    # ── 后处理校验：确保左右边框外侧有双层外框线 ──
    # 如果左边框外侧没有近距离伴随线(<间距*0.4)，说明可能选偏了
    # 尝试在候选中找更外侧一个间距处的线来扩展
    companion_max = min(80, spacing * 0.4)
    left_pos = result[0]["intercept"]
    right_pos = result[-1]["intercept"]

    has_left_outer = _has_companion(left_pos, v_clusters, "left", max_dist=companion_max, min_length=_companion_min_len)
    has_right_outer = _has_companion(right_pos, v_clusters, "right", max_dist=companion_max, min_length=_companion_min_len)

    # 扩展时不能超出安全边距（图片边缘 15% 范围内不扩展）
    # 对开页中分后，版心/中缝就在边缘附近
    edge_margin = img_width * 0.15

    if not has_left_outer:
        # 向左扩展：找距左边框约一个间距处的候选线
        for c in reversed(candidates):
            if c["intercept"] < edge_margin:
                continue  # 太靠近图片左边缘（可能是版心/中缝）
            d = left_pos - c["intercept"]
            if abs(d - spacing) < spacing * 0.3:
                # 检查这条线外侧是否有双层伴随
                if _has_companion(c["intercept"], v_clusters, "left", max_dist=companion_max, min_length=_companion_min_len):
                    result = [c] + result[:num_cols]
                    print(f"  左边框校正: 向左扩展到 x≈{c['intercept']:.0f}")
                    break

    if not has_right_outer:
        for c in candidates:
            if c["intercept"] > img_width - edge_margin:
                continue  # 太靠近图片右边缘
            d = c["intercept"] - right_pos
            if abs(d - spacing) < spacing * 0.3:
                if _has_companion(c["intercept"], v_clusters, "right", max_dist=companion_max, min_length=_companion_min_len):
                    result = result[1:] + [c]
                    print(f"  右边框校正: 向右扩展到 x≈{c['intercept']:.0f}")
                    break

    # ── 后处理校验2：收缩异常短的首尾线 ──
    # 版心线通常比正文界栏短得多（覆盖不了整个框高），
    # 如果首/尾线长度 < 内部线中位数的 85%，收缩掉
    interior_lengths = [c["total_length"] for c in result[1:-1]]
    med_interior = float(np.median(interior_lengths)) if interior_lengths else 0

    if med_interior > 0:
        if result[0]["total_length"] < med_interior * 0.85:
            print(f"  左边框收缩: x≈{result[0]['intercept']:.0f} "
                  f"长度{result[0]['total_length']:.0f} < "
                  f"内部中位数{med_interior:.0f}的85%")
            result = result[1:]
            # 补一条右侧的线
            right_pos = result[-1]["intercept"]
            spacing_est = (right_pos - result[0]["intercept"]) / (len(result) - 1)
            target = right_pos + spacing_est
            for c in candidates:
                if abs(c["intercept"] - target) < spacing_est * 0.3:
                    result.append(c)
                    break

        if len(result) == num_cols + 1 and result[-1]["total_length"] < med_interior * 0.85:
            print(f"  右边框收缩: x≈{result[-1]['intercept']:.0f} "
                  f"长度{result[-1]['total_length']:.0f} < "
                  f"内部中位数{med_interior:.0f}的85%")
            result = result[:-1]
            left_pos = result[0]["intercept"]
            spacing_est = (result[-1]["intercept"] - left_pos) / (len(result) - 1)
            target = left_pos - spacing_est
            for c in reversed(candidates):
                if abs(c["intercept"] - target) < spacing_est * 0.3:
                    result.insert(0, c)
                    break

    if len(result) != num_cols + 1:
        print(f"  校正后线数不对: {len(result)}, 需要 {num_cols + 1}")
        return None

    spacing = (result[-1]["intercept"] - result[0]["intercept"]) / num_cols
    span = result[-1]["intercept"] - result[0]["intercept"]

    print(f"  网格匹配成功: {n_needed} 条竖线, 间距≈{spacing:.1f}px, "
          f"偏差={_best_dev:.4f}, "
          f"跨度={span:.0f}px ({span/img_width*100:.0f}%宽)")
    return result


# ──────────────────────────────────────────────────────────────────
# 检测上下水平边框
# ──────────────────────────────────────────────────────────────────

def select_h_borders(
    h_clusters: list[dict],
    grid_v: list[dict],
    img_width: int,
    img_height: int,
    min_length_ratio: float = 0.3,
) -> tuple[dict | None, dict | None]:
    """检测与竖线相连的上下水平边框线。

    利用竖线 segments 的端点 y 坐标来推断边框位置，
    确保选出的横线确实是和竖线相连的框线，而不是页面边缘。
    """
    # 从竖线的 segments 推断上下边框的大致 y 位置
    # 竖线 axis='v' 时 segments 沿 y 轴
    top_ys = []
    bot_ys = []
    for v in grid_v:
        segs = v["segments"]
        if segs:
            top_ys.append(min(s for s, e in segs))
            bot_ys.append(max(e for s, e in segs))

    if not top_ys or not bot_ys:
        return None, None

    # 竖线起点/终点的中位数 = 边框 y 的估计
    est_top = float(np.median(top_ys))
    est_bot = float(np.median(bot_ys))
    frame_h = est_bot - est_top

    # 搜索容差：框架高度的 5%
    tol = frame_h * 0.05

    min_len = img_width * min_length_ratio
    candidates = [c for c in h_clusters if c["total_length"] >= min_len]
    if not candidates:
        return None, None

    # 找最接近 est_top 的横线
    top = None
    best_top_dist = float("inf")
    for c in candidates:
        d = abs(c["intercept"] - est_top)
        if d < tol and d < best_top_dist:
            best_top_dist = d
            top = c

    # 找最接近 est_bot 的横线
    bottom = None
    best_bot_dist = float("inf")
    for c in candidates:
        d = abs(c["intercept"] - est_bot)
        if d < tol and d < best_bot_dist:
            best_bot_dist = d
            bottom = c

    if top is not None:
        print(f"  上边框: y≈{top['intercept']:.0f} (竖线端点估计: {est_top:.0f})")
    if bottom is not None:
        print(f"  下边框: y≈{bottom['intercept']:.0f} (竖线端点估计: {est_bot:.0f})")

    return top, bottom


# ──────────────────────────────────────────────────────────────────
# 交点计算
# ──────────────────────────────────────────────────────────────────

def intersect_hv(h_slope, h_int, v_slope, v_int) -> tuple[float, float]:
    """水平线 y=h_slope*x+h_int 与 垂直线 x=v_slope*y+v_int 的交点。"""
    # 联立: y = h_slope*x + h_int,  x = v_slope*y + v_int
    # 代入: y = h_slope*(v_slope*y + v_int) + h_int
    # y*(1 - h_slope*v_slope) = h_slope*v_int + h_int
    denom = 1.0 - h_slope * v_slope
    if abs(denom) < 1e-12:
        return (0.0, 0.0)
    y = (h_slope * v_int + h_int) / denom
    x = v_slope * y + v_int
    return (x, y)


# ──────────────────────────────────────────────────────────────────
# 网格匹配主函数
# ──────────────────────────────────────────────────────────────────

def detect_grid(
    image: np.ndarray,
    num_cols: int,
) -> dict:
    """检测图像中的 N 列网格，返回网格信息（不做提取）。

    Returns:
        info dict, 成功时包含 "src_points", "grid_w", "grid_h" 等。
        失败时包含 "error"。
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    h, w = gray.shape
    info: dict = {"width": w, "height": h, "num_cols": num_cols}

    # 1. LSD 检测
    all_lines = detect_lines(gray)
    h_lines = [ln for ln in all_lines if ln["type"] == "horizontal"]
    v_lines = [ln for ln in all_lines if ln["type"] == "vertical"]

    if len(v_lines) < num_cols + 1:
        info["error"] = "竖线不足"
        return info

    # 2. 共线性聚类
    v_clusters = cluster_lines(v_lines, "v", pos_tol=15, max_gap=60)
    h_clusters = cluster_lines(h_lines, "h", pos_tol=15, max_gap=60)

    # 3. 选出等距竖线
    grid_v = select_grid_verticals(v_clusters, num_cols, w, h)
    if grid_v is None:
        info["error"] = "无法匹配等距竖线"
        return info

    # 4. 检测上下边框（基于竖线端点位置）
    top_h, bottom_h = select_h_borders(h_clusters, grid_v, w, h)
    if top_h is None or bottom_h is None:
        info["error"] = f"水平边框不全: top={'有' if top_h else '无'}, bottom={'有' if bottom_h else '无'}"
        return info

    # 5. 计算所有网格交点（源点）
    src_points = []
    for v in grid_v:
        pt_top = intersect_hv(top_h["slope"], top_h["intercept"],
                              v["slope"], v["intercept"])
        pt_bot = intersect_hv(bottom_h["slope"], bottom_h["intercept"],
                              v["slope"], v["intercept"])
        src_points.append(pt_top)
        src_points.append(pt_bot)

    # 网格原始尺寸（像素）
    grid_w = grid_v[-1]["intercept"] - grid_v[0]["intercept"]
    grid_h = bottom_h["intercept"] - top_h["intercept"]

    info["src_points"] = src_points
    info["grid_w"] = grid_w
    info["grid_h"] = grid_h

    return info


def extract_grid(
    image: np.ndarray,
    info: dict,
    output_size: tuple[int, int],
    debug: bool = False,
) -> tuple[np.ndarray | None, dict]:
    """根据检测到的网格信息，透视变换提取到指定尺寸。

    Args:
        image: 原始图像
        info: detect_grid 返回的 info（必须包含 src_points）
        output_size: (width, height) 标准输出尺寸
        debug: 是否生成调试图

    Returns:
        (校正后图像, 更新后的info)
    """
    if "error" in info or "src_points" not in info:
        return None, info

    num_cols = info["num_cols"]
    src_points = info["src_points"]
    out_w, out_h = output_size

    # 构建目标网格点
    col_w = out_w / num_cols
    dst_points = []
    for i in range(num_cols + 1):
        x = i * col_w
        dst_points.append((x, 0.0))
        dst_points.append((x, float(out_h)))

    src_pts = np.array(src_points, dtype=np.float32)
    dst_pts = np.array(dst_points, dtype=np.float32)

    # Homography 拟合
    H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
    if H is None:
        info["error"] = "Homography 拟合失败"
        return None, info

    inlier_count = int(mask.sum()) if mask is not None else 0
    info["homography_inliers"] = inlier_count
    info["homography_total"] = len(src_points)
    info["output_size"] = output_size

    # 透视变换
    result = cv2.warpPerspective(
        image, H, (out_w, out_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )

    # 调试可视化
    if debug:
        debug_img = image.copy()
        if len(debug_img.shape) == 2:
            debug_img = cv2.cvtColor(debug_img, cv2.COLOR_GRAY2BGR)

        for pt in src_points:
            cv2.circle(debug_img, (int(pt[0]), int(pt[1])), 5, (0, 0, 255), -1)

        for i in range(num_cols + 1):
            pt_top = src_points[i * 2]
            pt_bot = src_points[i * 2 + 1]
            cv2.line(debug_img,
                     (int(pt_top[0]), int(pt_top[1])),
                     (int(pt_bot[0]), int(pt_bot[1])),
                     (0, 255, 0), 2)

        for row_offset in [0, 1]:
            for i in range(num_cols):
                p1 = src_points[i * 2 + row_offset]
                p2 = src_points[(i + 1) * 2 + row_offset]
                cv2.line(debug_img,
                         (int(p1[0]), int(p1[1])),
                         (int(p2[0]), int(p2[1])),
                         (255, 0, 0), 2)

        info["debug_image"] = debug_img

    return result, info


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────

def _imread(path, flags=cv2.IMREAD_COLOR):
    img = cv2.imread(str(path), flags)
    if img is None:
        buf = np.fromfile(str(path), dtype=np.uint8)
        img = cv2.imdecode(buf, flags)
    return img


def _imwrite(path, img):
    ext = Path(path).suffix
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(str(path))


def _load_halves(img_path: Path, spread: bool) -> list[tuple[str, np.ndarray]]:
    """加载图片，返回 [(name, image), ...]。对开页会中分。"""
    image = _imread(str(img_path))
    if image is None:
        return []
    stem = img_path.stem
    if spread:
        h, w = image.shape[:2]
        mid = w // 2
        return [
            (f"{stem}_right", image[:, mid:]),
            (f"{stem}_left", image[:, :mid]),
        ]
    return [(stem, image)]


def main():
    parser = argparse.ArgumentParser(description="网格匹配算法测试")
    parser.add_argument("input", help="输入图片路径或目录")
    parser.add_argument("--cols", type=int, default=10, help="每页列数")
    parser.add_argument("--spread", action="store_true",
                        help="输入为对开页（先中分再分别匹配）")
    parser.add_argument("--output", "-o", help="输出目录（默认 output/_grid_test/）")
    parser.add_argument("--debug", action="store_true", help="输出调试可视化")
    args = parser.parse_args()

    input_path = Path(args.input)
    out_dir = Path(args.output) if args.output else _project_root / "output" / "_grid_test"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 收集所有图片
    if input_path.is_dir():
        img_paths = sorted(
            p for p in input_path.iterdir()
            if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".tif", ".tiff")
        )
    elif input_path.is_file():
        img_paths = [input_path]
    else:
        print(f"路径不存在: {input_path}")
        return 1

    # 展开为半页列表: [(name, image, img_path), ...]
    all_halves = []
    for p in img_paths:
        for name, img in _load_halves(p, args.spread):
            all_halves.append((name, img, p))

    if not all_halves:
        print("未找到图片")
        return 1

    print(f"共 {len(all_halves)} 个半页")

    # ── 第一遍：检测网格，收集尺寸 ──
    print("\n=== 第一遍：检测网格 ===")
    detections = []  # [(name, image, info), ...]
    grid_ws = []
    grid_hs = []

    for name, img, _ in all_halves:
        info = detect_grid(img, args.cols)
        detections.append((name, img, info))

        if "error" in info:
            print(f"  {name}: 失败 — {info['error']}")
        else:
            grid_ws.append(info["grid_w"])
            grid_hs.append(info["grid_h"])
            print(f"  {name}: 网格 {info['grid_w']:.0f}x{info['grid_h']:.0f}")

    if not grid_ws:
        print("\n所有页面检测失败")
        return 1

    # 计算标准尺寸（中位数）
    std_w = int(np.median(grid_ws))
    std_h = int(np.median(grid_hs))
    success_rate = len(grid_ws) / len(all_halves)

    print(f"\n=== 标准尺寸: {std_w} x {std_h} ===")
    print(f"检测成功: {len(grid_ws)}/{len(all_halves)} ({success_rate:.0%})")

    # ── 第二遍：统一提取 ──
    print("\n=== 第二遍：提取到标准尺寸 ===")
    for name, img, info in detections:
        if "error" in info:
            continue

        result, info = extract_grid(img, info, (std_w, std_h), debug=args.debug)

        if result is not None:
            out_path = out_dir / f"{name}.png"
            _imwrite(str(out_path), result)
            print(f"  {name}: {info['output_size']}, "
                  f"inliers={info['homography_inliers']}/{info['homography_total']}")
        else:
            print(f"  {name}: 提取失败 — {info.get('error', '未知')}")

        if args.debug and "debug_image" in info:
            dbg_path = out_dir / f"{name}_debug.png"
            _imwrite(str(dbg_path), info["debug_image"])

    print(f"\n输出目录: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
