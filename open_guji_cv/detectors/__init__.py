"""OCR 检测器（clustering.candidates 用 PaddleOCR 出候选）。

2026-10-06 cv 大清理（overview#413）：v1 的线、版框、列、字格检测器随 v1 管线删除。
"""

from .ocr_detector import OcrDetector, CharBox, WordBox

__all__ = ["OcrDetector", "CharBox", "WordBox"]
