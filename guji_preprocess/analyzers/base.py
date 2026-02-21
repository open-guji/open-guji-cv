"""分析器基类。"""

from abc import ABC, abstractmethod

import numpy as np


class BaseAnalyzer(ABC):
    """所有书级特征分析器的基类。

    每个分析器负责检测一个或一组相关的版式特征。
    analyze() 接收一组样本图片，返回检测到的特征字典。
    """

    name: str = "base"

    @abstractmethod
    def analyze(self, images: list[np.ndarray]) -> dict:
        """分析一组样本图片，返回检测到的特征。

        Args:
            images: BGR 格式的图像列表（通常 5~10 张样本）

        Returns:
            字典，包含检测到的特征和置信度。
            例如: {
                "color_mode": "bw",
                "_confidence": {"color_mode": 0.95}
            }
            以 '_' 开头的 key 为元信息，不直接映射到 BookProfile 字段。
        """
        ...
