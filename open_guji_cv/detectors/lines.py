"""LSD 线段检测器 —— 从 lsd_detect.py 提取核心逻辑。"""

from __future__ import annotations

import cv2
import numpy as np

from ..utils.image_io import imread


class LineDetector:
    """使用 LSD 算法检测图像中的线段。

    Args:
        min_length: 最小线段长度（像素）
        angle_tol: 判定水平/垂直的角度容差（度）
    """

    def __init__(self, min_length: int = 30, angle_tol: float = 10.0):
        self.min_length = min_length
        self.angle_tol = angle_tol

    def detect(self, image: np.ndarray) -> dict:
        """检测图像中的线段。

        Args:
            image: BGR 或灰度图像

        Returns:
            {
                "image_size": {"width": w, "height": h},
                "summary": {"total": N, "vertical": N, "horizontal": N, "other": N},
                "lines": [{"x1", "y1", "x2", "y2", "length", "width",
                           "type", "angle_from_vertical"}, ...]
            }
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        h, w = gray.shape

        lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
        lines, widths, precs, nfas = lsd.detect(gray)

        if lines is None:
            return {
                "image_size": {"width": w, "height": h},
                "summary": {"total": 0, "vertical": 0, "horizontal": 0, "other": 0},
                "lines": [],
            }

        all_lines = []
        counts = {"vertical": 0, "horizontal": 0, "other": 0}

        for i, line in enumerate(lines):
            x1, y1, x2, y2 = line[0]
            dx = x2 - x1
            dy = y2 - y1
            length = np.sqrt(dx * dx + dy * dy)

            if length < self.min_length:
                continue

            width = float(widths[i][0]) if widths is not None else 1.0
            nfa = float(nfas[i][0]) if nfas is not None else 0.0
            angle_from_vert = abs(np.degrees(np.arctan2(abs(dx), abs(dy))))

            if angle_from_vert <= self.angle_tol:
                line_type = "vertical"
            elif angle_from_vert >= (90 - self.angle_tol):
                line_type = "horizontal"
            else:
                line_type = "other"

            counts[line_type] += 1

            all_lines.append({
                "x1": float(x1), "y1": float(y1),
                "x2": float(x2), "y2": float(y2),
                "length": float(length),
                "width": width,
                "nfa": nfa,
                "angle_from_vertical": float(angle_from_vert),
                "type": line_type,
            })

        return {
            "image_size": {"width": w, "height": h},
            "summary": {
                "total": len(all_lines),
                "vertical": counts["vertical"],
                "horizontal": counts["horizontal"],
                "other": counts["other"],
            },
            "lines": all_lines,
        }

    def detect_from_file(self, image_path: str) -> dict:
        """从文件路径检测线段。"""
        img = imread(image_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise FileNotFoundError(f"无法读取图片: {image_path}")
        return self.detect(img)
