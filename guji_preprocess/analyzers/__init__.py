"""Phase 1: 书级特征分析器注册表。"""

from .base import BaseAnalyzer
from .color_mode import ColorModeAnalyzer
from .page_layout import PageLayoutAnalyzer
from .interference import InterferenceAnalyzer

# 分析器注册表：按顺序执行
ANALYZERS: list[type[BaseAnalyzer]] = [
    ColorModeAnalyzer,
    PageLayoutAnalyzer,
    InterferenceAnalyzer,
]


def get_all_analyzers() -> list[BaseAnalyzer]:
    """获取所有注册的分析器实例。"""
    return [cls() for cls in ANALYZERS]


__all__ = [
    "BaseAnalyzer",
    "ColorModeAnalyzer",
    "PageLayoutAnalyzer",
    "InterferenceAnalyzer",
    "ANALYZERS",
    "get_all_analyzers",
]
