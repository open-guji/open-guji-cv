"""Phase 2: 图像预处理器注册表。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import BasePreprocessor
from .split_page import SplitPagePreprocessor
from .crop_margin import CropMarginPreprocessor
from .crop_spine import CropSpinePreprocessor
from .binarize import BinarizePreprocessor
from .normalize import NormalizePreprocessor

if TYPE_CHECKING:
    from ..profile import BookProfile

# 预处理器注册表：按执行顺序排列
# 顺序很重要：先拆分/裁剪，再二值化，最后矫正
PREPROCESSORS: list[type[BasePreprocessor]] = [
    SplitPagePreprocessor,
    CropMarginPreprocessor,
    CropSpinePreprocessor,
    BinarizePreprocessor,
    NormalizePreprocessor,
]


def get_preprocessors(profile: BookProfile) -> list[BasePreprocessor]:
    """根据 BookProfile 获取需要执行的预处理器实例列表。"""
    return [cls() for cls in PREPROCESSORS if cls.is_needed(profile)]


__all__ = [
    "BasePreprocessor",
    "SplitPagePreprocessor",
    "CropMarginPreprocessor",
    "CropSpinePreprocessor",
    "BinarizePreprocessor",
    "NormalizePreprocessor",
    "PREPROCESSORS",
    "get_preprocessors",
]
