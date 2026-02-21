"""图像 IO 工具，支持 Windows 非 ASCII 路径。"""

from pathlib import Path

import cv2
import numpy as np


def imread(image_path: str, flags=cv2.IMREAD_COLOR) -> np.ndarray | None:
    """读取图片，支持 Windows 非 ASCII 路径。"""
    img = cv2.imread(str(image_path), flags)
    if img is None:
        buf = np.fromfile(str(image_path), dtype=np.uint8)
        img = cv2.imdecode(buf, flags)
    return img


def imwrite(path: str, img: np.ndarray) -> bool:
    """写入图片，支持 Windows 非 ASCII 路径。"""
    ext = Path(path).suffix
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(str(path))
        return True
    return False
