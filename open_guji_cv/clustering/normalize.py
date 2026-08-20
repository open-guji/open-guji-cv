"""M2 图块归一化：灰度图块 → 标准 S×S 二值字形图。

流程（设计文档 6.1）：
1. Sauvola 局部二值化（与 s6 预处理解耦，参数独立）
2. 去边缘毛刺：删除贴边且面积过小的连通域（界行/相邻字残留）
3. 墨迹外接框等比缩放 + 质心居中，四周留白
4. 输出 uint8 {0,1} 二值图（1=墨迹）
"""

from __future__ import annotations

import cv2
import numpy as np

NORM_SIZE = 64          # 归一化边长 S
MARGIN_RATIO = 0.12     # 四周留白比例
NOISE_AREA = 6          # 贴边小连通域面积阈值（像素）
SAUVOLA_WINDOW = 31
SAUVOLA_K = 0.2


def sauvola_binarize(gray: np.ndarray, window: int = SAUVOLA_WINDOW,
                     k: float = SAUVOLA_K) -> np.ndarray:
    """Sauvola 局部阈值二值化。返回 uint8 {0,1}，1=墨迹（暗像素）。"""
    g = gray.astype(np.float64)
    mean = cv2.boxFilter(g, ddepth=-1, ksize=(window, window),
                         borderType=cv2.BORDER_REPLICATE)
    sq_mean = cv2.boxFilter(g * g, ddepth=-1, ksize=(window, window),
                            borderType=cv2.BORDER_REPLICATE)
    std = np.sqrt(np.maximum(sq_mean - mean * mean, 0.0))
    R = 128.0
    thresh = mean * (1.0 + k * (std / R - 1.0))
    return (g < thresh).astype(np.uint8)


def remove_edge_specks(binary: np.ndarray, noise_area: int = NOISE_AREA) -> np.ndarray:
    """删除切分/裁切残留：

    - 贴边且面积 < noise_area 的毛刺；
    - 贴左右边、细而高的贯穿竖线（界行残留）；
    - 贴上下边、扁而宽的贯穿横线（相邻字/边框残留）。
    """
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 1:
        return binary
    h, w = binary.shape
    out = binary.copy()
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        touches_lr = (x == 0 or x + bw >= w)
        touches_tb = (y == 0 or y + bh >= h)
        speck = (touches_lr or touches_tb) and area < noise_area
        vline = touches_lr and bw <= 0.16 * w and bh >= 0.55 * h
        hline = touches_tb and bh <= 0.16 * h and bw >= 0.55 * w
        # 浅入侵残片：相邻字/界行被切进来的边缘碎块。图块有 padding 外扩，
        # 本字主体连通域不会既贴边又这么浅。
        shallow_tb = touches_tb and bh <= 0.20 * h
        shallow_lr = touches_lr and bw <= 0.20 * w
        if speck or vline or hline or shallow_tb or shallow_lr:
            out[labels == i] = 0
    return out


def _drop_stray_components(binary: np.ndarray,
                           keep_ink_ratio: float = 0.98) -> np.ndarray:
    """稳健化墨迹：按面积从大到小累计到 keep_ink_ratio 的连通域保留，
    其余小残片（相邻字一角、噪点）删除 —— 防止外接框被残片撑大。"""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 2:
        return binary
    areas = stats[1:, cv2.CC_STAT_AREA]
    order = np.argsort(-areas)
    total = areas.sum()
    keep: set[int] = set()
    acc = 0
    for k in order:
        keep.add(k + 1)
        acc += areas[k]
        if acc >= total * keep_ink_ratio:
            break
    out = binary.copy()
    drop_mask = ~np.isin(labels, list(keep)) & (binary > 0)
    out[drop_mask] = 0
    return out


def ink_bbox(binary: np.ndarray) -> tuple[int, int, int, int] | None:
    """墨迹外接框 (x0, y0, x1, y1)，无墨迹返回 None。x1/y1 为开区间。"""
    ys, xs = np.nonzero(binary)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def normalize_patch(gray: np.ndarray, size: int = NORM_SIZE,
                    margin_ratio: float = MARGIN_RATIO,
                    noise_area: int = NOISE_AREA,
                    stroke_width: int | None = 3) -> np.ndarray:
    """灰度图块 → S×S uint8 {0,1} 归一二值图。

    墨迹外接框等比缩放到内容区（size × (1 - 2*margin)），
    再平移使墨迹质心对准图心（clamp 保证不出界）。
    空图块（无墨迹）返回全零。
    """
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    binary = sauvola_binarize(gray)
    binary = remove_edge_specks(binary, noise_area)

    binary = _drop_stray_components(binary)
    bbox = ink_bbox(binary)
    out = np.zeros((size, size), dtype=np.uint8)
    if bbox is None:
        return out
    x0, y0, x1, y1 = bbox
    crop = binary[y0:y1, x0:x1]

    content = max(1, int(round(size * (1.0 - 2.0 * margin_ratio))))
    ch, cw = crop.shape
    # 受限各向异性缩放：以等比为基准，每轴允许 ±20% 拉伸把外接框
    # 撑满内容区 —— 抵消切分抖动造成的 bbox 纵横比噪声，
    # 又不至于把「一/亅」这类极端纵横比的字拉成一样。
    scale = content / max(ch, cw)
    sy = min(max(content / ch, scale * 0.8), scale * 1.25)
    sx = min(max(content / cw, scale * 0.8), scale * 1.25)
    nh = max(1, min(size, int(round(ch * sy))))
    nw = max(1, min(size, int(round(cw * sx))))
    resized = cv2.resize(crop.astype(np.uint8) * 255, (nw, nh),
                         interpolation=cv2.INTER_AREA)
    resized = (resized > 127).astype(np.uint8)

    # 先按几何中心摆放，再按质心微调
    ys, xs = np.nonzero(resized)
    if len(xs) == 0:
        return out
    cy, cx = float(ys.mean()), float(xs.mean())
    top = int(round(size / 2.0 - cy))
    left = int(round(size / 2.0 - cx))
    top = min(max(top, 0), size - nh)
    left = min(max(left, 0), size - nw)
    out[top:top + nh, left:left + nw] = resized
    if stroke_width:
        out = stroke_normalize(out, stroke_width)
    return out


def _thin_once(img: np.ndarray, step: int) -> np.ndarray:
    """Zhang-Suen 细化的一个子迭代（向量化）。img: uint8 {0,1}。"""
    p = np.pad(img, 1)
    p2 = p[:-2, 1:-1]; p3 = p[:-2, 2:]; p4 = p[1:-1, 2:]
    p5 = p[2:, 2:];   p6 = p[2:, 1:-1]; p7 = p[2:, :-2]
    p8 = p[1:-1, :-2]; p9 = p[:-2, :-2]
    neigh = [p2, p3, p4, p5, p6, p7, p8, p9]
    B = sum(n.astype(np.int32) for n in neigh)
    ring = neigh + [p2]
    A = sum(((ring[i] == 0) & (ring[i + 1] == 1)).astype(np.int32)
            for i in range(8))
    if step == 0:
        cond = (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
    else:
        cond = (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
    remove = (img == 1) & (B >= 2) & (B <= 6) & (A == 1) & cond
    out = img.copy()
    out[remove] = 0
    return out


def skeletonize(binary: np.ndarray, max_iter: int = 20) -> np.ndarray:
    """Zhang-Suen 骨架化。输入/输出 uint8 {0,1}。"""
    img = binary.astype(np.uint8)
    for _ in range(max_iter):
        nxt = _thin_once(_thin_once(img, 0), 1)
        if np.array_equal(nxt, img):
            break
        img = nxt
    return img


def stroke_normalize(binary: np.ndarray, stroke_width: int = 3) -> np.ndarray:
    """笔宽归一：骨架化 + 统一膨胀到固定笔宽。

    刻本不同印次着墨浓淡不同（同字笔画可差 2 倍宽），墨迹 F1 对此极敏感；
    归一到统一笔宽后，同字 F1 主要反映骨架形状差异——这才是字形本身。
    副作用：膨胀还能桥接 1~2px 的笔画断裂（磨损容忍）。
    """
    skel = skeletonize(binary)
    if not skel.any():
        return skel
    k = max(1, stroke_width)
    kernel = np.ones((k, k), dtype=np.uint8)
    return cv2.dilate(skel, kernel)


def soft_patch(binary: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    """归一二值图 → 轻度模糊的 float32 图（特征提取用，抗锯齿/微形变）。"""
    f = binary.astype(np.float32)
    return cv2.GaussianBlur(f, ksize=(0, 0), sigmaX=sigma)
