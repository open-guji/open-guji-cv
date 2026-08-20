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
    """删除贴边且面积 < noise_area 的连通域（界行残留、切边毛刺）。"""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 1:
        return binary
    h, w = binary.shape
    out = binary.copy()
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        touches_edge = (x == 0 or y == 0 or x + bw >= w or y + bh >= h)
        if touches_edge and area < noise_area:
            out[labels == i] = 0
    return out


def ink_bbox(binary: np.ndarray) -> tuple[int, int, int, int] | None:
    """墨迹外接框 (x0, y0, x1, y1)，无墨迹返回 None。x1/y1 为开区间。"""
    ys, xs = np.nonzero(binary)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def normalize_patch(gray: np.ndarray, size: int = NORM_SIZE,
                    margin_ratio: float = MARGIN_RATIO,
                    noise_area: int = NOISE_AREA) -> np.ndarray:
    """灰度图块 → S×S uint8 {0,1} 归一二值图。

    墨迹外接框等比缩放到内容区（size × (1 - 2*margin)），
    再平移使墨迹质心对准图心（clamp 保证不出界）。
    空图块（无墨迹）返回全零。
    """
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    binary = sauvola_binarize(gray)
    binary = remove_edge_specks(binary, noise_area)

    bbox = ink_bbox(binary)
    out = np.zeros((size, size), dtype=np.uint8)
    if bbox is None:
        return out
    x0, y0, x1, y1 = bbox
    crop = binary[y0:y1, x0:x1]

    content = max(1, int(round(size * (1.0 - 2.0 * margin_ratio))))
    ch, cw = crop.shape
    scale = content / max(ch, cw)
    nh = max(1, int(round(ch * scale)))
    nw = max(1, int(round(cw * scale)))
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
    return out


def soft_patch(binary: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    """归一二值图 → 轻度模糊的 float32 图（特征提取用，抗锯齿/微形变）。"""
    f = binary.astype(np.float32)
    return cv2.GaussianBlur(f, ksize=(0, 0), sigmaX=sigma)
