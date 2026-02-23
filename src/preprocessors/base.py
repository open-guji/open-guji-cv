"""预处理器基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ..profile import BookProfile


class BasePreprocessor(ABC):
    """所有图像预处理器的基类。

    每个预处理器负责一项特定的图像预处理操作。
    Pipeline 根据 BookProfile 决定启用哪些预处理器。

    process() 返回值约定：
    - 单张 np.ndarray：一对一处理，保持原文件名
    - list[tuple[str, np.ndarray]]：一对多拆分，每个元素为 (后缀名, 图像)
      例如 [("right", img1), ("left", img2)] → 生成 {stem}_right.png, {stem}_left.png
    """

    name: str = "base"

    # 执行优先级，数值越小越先执行
    priority: int = 100

    @classmethod
    @abstractmethod
    def is_needed(cls, profile: BookProfile) -> bool:
        """根据 BookProfile 判断是否需要执行此预处理器。"""
        ...

    @abstractmethod
    def process(self, image: np.ndarray, profile: BookProfile
                ) -> np.ndarray | list[tuple[str, np.ndarray]]:
        """处理单张图片。

        Args:
            image: BGR 格式图像
            profile: 当前书的版式特征

        Returns:
            处理后的图像（单张），或命名子图列表用于拆分。
        """
        ...
