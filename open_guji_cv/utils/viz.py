"""可视化绘制辅助工具。"""

import cv2
import numpy as np


def draw_line(img: np.ndarray, pt1: tuple, pt2: tuple,
              color: tuple, thickness: int = 2):
    """在图像上绘制线段。"""
    cv2.line(img, (int(pt1[0]), int(pt1[1])),
             (int(pt2[0]), int(pt2[1])), color, thickness)


def draw_rect(img: np.ndarray, x1: int, y1: int, x2: int, y2: int,
              color: tuple, thickness: int = 2):
    """在图像上绘制矩形。"""
    cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)


def draw_text(img: np.ndarray, text: str, pos: tuple,
              color: tuple = (0, 0, 0), scale: float = 0.5):
    """在图像上绘制文字。"""
    cv2.putText(img, text, (int(pos[0]), int(pos[1])),
                cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1)


def overlay_blend(base: np.ndarray, overlay: np.ndarray,
                  alpha: float = 0.3) -> np.ndarray:
    """半透明叠加两张图像。"""
    return cv2.addWeighted(overlay, alpha, base, 1 - alpha, 0)
