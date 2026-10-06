"""字块形态量：墨外接框尺寸、笔粗（墨面积 / 骨架长）、相对笔粗。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.clustering.normalize import skeletonize


def stroke_stats(binary: np.ndarray) -> dict | None:
    """binary: uint8 {0,1}，1=墨。"""
    ys, xs = np.nonzero(binary)
    if len(xs) < 5:
        return None
    H = int(ys.max() - ys.min() + 1)
    W = int(xs.max() - xs.min() + 1)
    sk = skeletonize(binary, max_iter=200)
    L = max(1, int(np.count_nonzero(sk)))
    area = int(len(xs))
    sw = area / L
    return {"H": H, "W": W, "size": max(H, W), "area": area, "sw": sw,
            "sw_rel": sw / max(H, W), "ink_bbox": area / (H * W)}


def stroke_width_dt(binary: np.ndarray, smooth: int = 0) -> float | None:
    """笔粗的第二种量法：距离变换在骨架上的中位 ×2。`smooth`>0 先中值滤波去毛边
    （全唐文 JB2 边缘毛刺会让骨架长出一堆短刺、面积/骨架长的量法偏小）。"""
    import cv2
    b = binary.astype(np.uint8)
    if smooth:
        b = (cv2.medianBlur(b * 255, smooth) > 127).astype(np.uint8)
    if b.sum() < 5:
        return None
    sk = skeletonize(b, max_iter=200) > 0
    dt = cv2.distanceTransform(b, cv2.DIST_L2, 5)
    v = dt[sk]
    return float(2 * np.median(v)) if len(v) else None
