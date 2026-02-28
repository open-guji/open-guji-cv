"""预处理步骤注册表。

定义步骤化管线：每步有固定编号、名称、条件，按顺序执行。
跳过的步骤不产生输出文件夹，下游步骤自动从最近的上游输出读取。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .base import BasePreprocessor
from .crop_spine import CropSpinePreprocessor
from .crop_margin import CropMarginPreprocessor
from .enhance_lines import EnhanceLinesPreprocessor
from .normalize import NormalizePreprocessor
from .split_page import SplitPagePreprocessor
from .binarize import BinarizePreprocessor

if TYPE_CHECKING:
    from ..profile import BookProfile


@dataclass
class StepDef:
    """一个预处理步骤的定义。"""
    number: int                              # 步骤编号 (s1, s2, ...)
    name: str                                # 步骤名称
    preprocessor_cls: type[BasePreprocessor]  # 预处理器类
    condition: Callable[[BookProfile], bool]  # 执行条件

    @property
    def folder_name(self) -> str:
        return f"s{self.number}_{self.name}"

    def is_needed(self, profile: BookProfile) -> bool:
        return self.condition(profile)

    def create_preprocessor(self) -> BasePreprocessor:
        return self.preprocessor_cls()


# ── 步骤注册表：按执行顺序排列 ──
# s1: 裁书脊阴影（条件：检测到书脊阴影）
# s2: 裁到边框（始终执行）
# s3: 长直线增强（始终执行，断续补全+线宽统一）
# s4: 倾斜校正（始终执行，内部判断是否需要旋转）
# s5: 拆分半页（条件：未剪切筒子页）
# s6: 二值化（始终执行）

STEPS: list[StepDef] = [
    StepDef(1, "crop_spine",     CropSpinePreprocessor,     lambda p: p.has_spine_shadow),
    StepDef(2, "crop_border",    CropMarginPreprocessor,    lambda p: True),
    StepDef(3, "enhance_lines",  EnhanceLinesPreprocessor,  lambda p: True),
    StepDef(4, "deskew",         NormalizePreprocessor,     lambda p: True),
    StepDef(5, "split",          SplitPagePreprocessor,     lambda p: p.is_uncut),
    StepDef(6, "binarize",       BinarizePreprocessor,      lambda p: True),
]


def get_active_steps(profile: BookProfile) -> list[StepDef]:
    """根据 BookProfile 获取需要执行的步骤列表。"""
    return [s for s in STEPS if s.is_needed(profile)]


# ── 向后兼容 ──

PREPROCESSORS: list[type[BasePreprocessor]] = [
    s.preprocessor_cls for s in STEPS
]


def get_preprocessors(profile: BookProfile) -> list[BasePreprocessor]:
    """向后兼容：返回需要执行的预处理器实例列表。"""
    return [s.create_preprocessor() for s in STEPS if s.is_needed(profile)]


__all__ = [
    "BasePreprocessor",
    "StepDef",
    "STEPS",
    "get_active_steps",
    "SplitPagePreprocessor",
    "CropMarginPreprocessor",
    "CropSpinePreprocessor",
    "EnhanceLinesPreprocessor",
    "BinarizePreprocessor",
    "NormalizePreprocessor",
    "PREPROCESSORS",
    "get_preprocessors",
]
