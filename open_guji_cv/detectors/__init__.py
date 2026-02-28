"""版面结构与字符检测器。"""

from .lines import LineDetector
from .borders import BorderDetector
from .columns import ColumnDetector
from .ocr_detector import OcrDetector, CharBox, WordBox
from .char_grid import CharGridDetector

__all__ = [
    "LineDetector",
    "BorderDetector",
    "ColumnDetector",
    "OcrDetector",
    "CharBox",
    "WordBox",
    "CharGridDetector",
]
