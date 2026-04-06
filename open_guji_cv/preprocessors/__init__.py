"""预处理步骤注册表。

定义步骤化管线：每步有固定编号、名称、条件，按顺序执行。
跳过的步骤不产生输出文件夹，下游步骤自动从最近的上游输出读取。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .base import BasePreprocessor
from .crop_margin import CropMarginPreprocessor
from .enhance_lines import EnhanceLinesPreprocessor
from .normalize import NormalizePreprocessor
from .split_page import SplitPagePreprocessor
from .binarize import BinarizePreprocessor
from .remove_watermark import RemoveWatermarkPreprocessor

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
        if self.name in profile.skip_steps:
            return False
        return self.condition(profile)

    def create_preprocessor(self) -> BasePreprocessor:
        return self.preprocessor_cls()


# ── 步骤注册表 ──
#
# 三种 pipeline 布局（由 page_type 决定）：
#
# cut_half（已裁半页）：校正 → 裁切 → 增强 → 二值化
# uncut_full（筒子页）：校正 → 裁切 → 增强 → 拆分 → 二值化
# spread（对开拍照）：  拆分 → 校正 → 裁切 → 增强 → 二值化
#
# 设计原则：
# 1. 校正（deskew）最先做，确保边框线横平竖直，后续步骤都更简单
# 2. 裁切（crop）一步完成：去除黑边、邻页残留、天头地脚，裁到正文区
#    原来的 crop_spine 不再需要——邻页残留和书脊阴影都在边框线外面，
#    统一裁到边框线即可去掉
# 3. spread 先拆分，因为中缝是最显著的特征

# 默认步骤表（cut_half / uncut_full 共用）
STEPS: list[StepDef] = [
    StepDef(1, "remove_watermark", RemoveWatermarkPreprocessor, lambda p: "watermark" in p.interferences),
    StepDef(2, "deskew",         NormalizePreprocessor,     lambda p: True),
    StepDef(3, "crop",           CropMarginPreprocessor,    lambda p: True),
    StepDef(4, "enhance_lines",  EnhanceLinesPreprocessor,  lambda p: True),
    StepDef(5, "split",          SplitPagePreprocessor,     lambda p: p.is_uncut),
    StepDef(6, "binarize",       BinarizePreprocessor,      lambda p: not p.is_colored),
]

# spread 模式步骤表：先拆分，再逐半页处理
STEPS_SPREAD: list[StepDef] = [
    StepDef(1, "remove_watermark", RemoveWatermarkPreprocessor, lambda p: "watermark" in p.interferences),
    StepDef(2, "split",          SplitPagePreprocessor,     lambda p: True),
    StepDef(3, "deskew",         NormalizePreprocessor,     lambda p: True),
    StepDef(4, "crop",           CropMarginPreprocessor,    lambda p: True),
    StepDef(5, "enhance_lines",  EnhanceLinesPreprocessor,  lambda p: True),
    StepDef(6, "binarize",       BinarizePreprocessor,      lambda p: not p.is_colored),
]


def get_steps(profile: BookProfile) -> list[StepDef]:
    """根据 BookProfile 获取步骤列表。"""
    if profile.is_spread:
        return STEPS_SPREAD
    return STEPS


def get_active_steps(profile: BookProfile) -> list[StepDef]:
    """根据 BookProfile 获取需要执行的步骤列表。"""
    return [s for s in get_steps(profile) if s.is_needed(profile)]


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
    "EnhanceLinesPreprocessor",
    "BinarizePreprocessor",
    "NormalizePreprocessor",
    "RemoveWatermarkPreprocessor",
    "PREPROCESSORS",
    "get_preprocessors",
]
