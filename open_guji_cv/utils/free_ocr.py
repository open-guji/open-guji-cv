"""自由版式：逐列送 PaddleOCR（3.x，PP-OCR 检测＋识别）读文本行，给切字定区、定字数。

识别软件对竖排一列能分出大字行和并排的小注行（小注行窄、两行并排），还读出每行几个字；
它的弱点是漏行、把一对小注横着读成一行。所以这里只出「行框＋文字＋置信度」，
怎么用、信不信由 `free_cells.segment_ocr` 定，漏掉的墨照旧走规则。

懒加载：没装 paddleocr 时 `available()` 为假，调用方别建 `LineReader`。"""

from __future__ import annotations

import importlib.util

import numpy as np

Line = tuple[int, int, int, int, str, float]     # x0, y0, x1, y1（图内左上原点）, 文字, 置信度


def available() -> bool:
    return importlib.util.find_spec("paddleocr") is not None


def engine_name() -> str:
    from importlib.metadata import version
    return f"paddleocr-{version('paddleocr')}"


class LineReader:
    """PaddleOCR 封装：一张列图 → 文本行。模型首次用时才加载。"""

    def __init__(self, device: str = "cpu"):
        self.device = device
        self._ocr = None

    def read(self, gray: np.ndarray) -> list[Line]:
        if self._ocr is None:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False,
                                  use_textline_orientation=False, device=self.device)
        img = np.dstack([gray] * 3) if gray.ndim == 2 else gray
        out: list[Line] = []
        for res in self._ocr.predict(img):
            r = res.json["res"]
            for b, t, s in zip(r.get("rec_boxes", []), r.get("rec_texts", []), r.get("rec_scores", [])):
                x0, y0, x1, y1 = (int(v) for v in b)
                out.append((x0, y0, x1, y1, str(t), float(s)))
        return out
