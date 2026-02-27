"""PaddleOCR 3.x 封装 —— 提供单列/整图字符检测。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class CharBox:
    """单个字符检测结果。"""
    polygon: list[list[float]]   # 4 点多边形 [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
    text: str
    confidence: float
    center_x: float
    center_y: float
    width: float
    height: float


@dataclass
class WordBox:
    """单字检测结果（来自 return_word_box）。"""
    text: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    center_y: float
    height: float


class OcrDetector:
    """PaddleOCR 3.x 封装。

    延迟初始化：首次调用 detect_chars 时才加载模型，
    避免 import 时就触发 PaddleOCR 的重量级初始化。
    """

    def __init__(self):
        self._ocr = None

    def _ensure_ocr(self):
        """延迟加载 PaddleOCR 模型。"""
        if self._ocr is not None:
            return
        # Windows + paddlepaddle-gpu 需要在 import paddle 前注册 nvidia DLL 目录
        import os, sys
        if sys.platform == "win32":
            import site as _site
            sp = _site.getsitepackages()
            for sp_dir in sp:
                nv = os.path.join(sp_dir, "nvidia")
                if os.path.isdir(nv):
                    for sub in os.listdir(nv):
                        for d in ("bin", "lib"):
                            dp = os.path.join(nv, sub, d)
                            if os.path.isdir(dp):
                                os.add_dll_directory(dp)
                    break
        from paddleocr import PaddleOCR
        self._ocr = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            lang="chinese_cht",
            text_det_thresh=0.3,
            text_det_box_thresh=0.5,
            device="gpu",
        )

    def detect_chars(self, image: np.ndarray) -> list[CharBox]:
        """检测图像中所有字符，返回 CharBox 列表（行级别）。"""
        self._ensure_ocr()

        results = list(self._ocr.predict(image))
        if not results:
            return []

        boxes: list[CharBox] = []
        for res in results:
            data = res.json
            if "res" not in data:
                continue

            dt_polys = data["res"].get("dt_polys", [])
            rec_texts = data["res"].get("rec_texts", [])
            rec_scores = data["res"].get("rec_scores", [])

            for i, poly in enumerate(dt_polys):
                text = rec_texts[i] if i < len(rec_texts) else ""
                score = rec_scores[i] if i < len(rec_scores) else 0.0

                poly_arr = np.array(poly, dtype=np.float64)
                xs = poly_arr[:, 0]
                ys = poly_arr[:, 1]

                boxes.append(CharBox(
                    polygon=poly,
                    text=text,
                    confidence=float(score),
                    center_x=float(np.mean(xs)),
                    center_y=float(np.mean(ys)),
                    width=float(np.max(xs) - np.min(xs)),
                    height=float(np.max(ys) - np.min(ys)),
                ))

        boxes.sort(key=lambda b: b.center_y)
        return boxes

    def detect_words(self, image: np.ndarray) -> list[WordBox]:
        """检测图像中所有单字，返回 WordBox 列表（字级别）。

        使用 return_word_box=True 让 PaddleOCR 基于 CTC 解码
        返回每个单字的位置估算。
        """
        self._ensure_ocr()

        results = list(self._ocr.predict(image, return_word_box=True))
        if not results:
            return []

        words: list[WordBox] = []
        for res in results:
            data = res.json
            if "res" not in data:
                continue

            text_words = data["res"].get("text_word", [])
            word_boxes = data["res"].get("text_word_boxes", [])

            # text_words 和 word_boxes 是按行组织的列表
            # text_words[i] = ['字1', '字2', ...] 第 i 行的单字列表
            # word_boxes[i] = [[x1,y1,x2,y2], ...] 第 i 行的单字框列表
            for line_idx in range(len(text_words)):
                chars = text_words[line_idx]
                boxes = word_boxes[line_idx] if line_idx < len(word_boxes) else []

                for j, char in enumerate(chars):
                    if j >= len(boxes):
                        break
                    box = boxes[j]
                    x_min, y_min, x_max, y_max = box[0], box[1], box[2], box[3]
                    h = y_max - y_min
                    cy = (y_min + y_max) / 2

                    words.append(WordBox(
                        text=char,
                        x_min=float(x_min),
                        y_min=float(y_min),
                        x_max=float(x_max),
                        y_max=float(y_max),
                        center_y=float(cy),
                        height=float(h),
                    ))

        words.sort(key=lambda w: w.center_y)
        return words
