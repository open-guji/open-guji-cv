"""边框检测器 —— 从 border_detect.py 提取核心逻辑。

识别双层边框（外粗内细）和内部列间界栏。
详细算法参见 border_detect.py。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ..profile import BookProfile

# 复用 border_detect.py 中的核心函数
# 为避免代码重复，直接导入现有模块
import sys
from pathlib import Path

# 将项目根目录加入 path，以便导入 border_detect
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from border_detect import (
    cluster_lines,
    detect_borders as _detect_borders_raw,
)


class BorderDetector:
    """古籍边框检测器。

    识别双层外边框和内部列间界栏。

    Args:
        pos_tol: 位置聚类容差（像素）
        max_gap: 断续线段合并最大间隙（像素）
        min_coverage_ratio: 边框线最小覆盖比
        layer_max_dist: 双层边框层间最大距离（像素）
    """

    def __init__(self, pos_tol: float = 15, max_gap: float = 60,
                 min_coverage_ratio: float = 0.3,
                 layer_max_dist: float = 80):
        self.pos_tol = pos_tol
        self.max_gap = max_gap
        self.min_coverage_ratio = min_coverage_ratio
        self.layer_max_dist = layer_max_dist

    def detect(self, lsd_data: dict, img_width: int, img_height: int,
               profile: BookProfile | None = None) -> dict:
        """从 LSD 数据中识别边框结构。

        Args:
            lsd_data: LineDetector 的输出
            img_width: 图像宽度
            img_height: 图像高度
            profile: 可选的 BookProfile，用于提供先验约束

        Returns:
            边框检测结果字典（与 border_detect.py 输出格式一致）
        """
        # 如果有 profile，可以用先验知识调整参数
        pos_tol = self.pos_tol
        max_gap = self.max_gap
        min_coverage = self.min_coverage_ratio
        layer_max_dist = self.layer_max_dist

        if profile is not None:
            # 磨损严重时放宽容差
            if profile.border_wear == "heavy":
                pos_tol *= 1.3
                max_gap *= 1.5
                min_coverage *= 0.7

        result = _detect_borders_raw(
            lsd_data, img_width, img_height,
            pos_tol=pos_tol, max_gap=max_gap,
            min_coverage_ratio=min_coverage,
            layer_max_dist=layer_max_dist,
        )

        # 如果有先验行数信息，验证检测到的列数
        if profile is not None and result.get("num_columns"):
            expected_cols = profile.lines_per_page
            detected_cols = result["num_columns"]
            if detected_cols != expected_cols:
                result["_column_mismatch"] = {
                    "expected": expected_cols,
                    "detected": detected_cols,
                }

        # 列编号：从右到左、从 1 开始（古籍竖排阅读顺序）
        # border_detect.py 底层按 x 坐标从左到右生成 index 0,1,2,...
        # 这里反转编号使最右列为 1，最左列为 N
        self._renumber_columns_rtl(result)

        return result

    @staticmethod
    def _renumber_columns_rtl(result: dict) -> None:
        """将列编号从左到右(0-based)改为从右到左(1-based)。

        古籍竖排文字从右往左阅读，第 1 列在最右侧。
        列的物理位置（left_x, right_x）不变，只改 index。
        column_dividers 的顺序也反转以与列编号对应。
        """
        columns = result.get("columns", [])
        if not columns:
            return

        n = len(columns)
        for col in columns:
            col["index"] = n - col["index"]  # 0→N, 1→N-1, ..., N-1→1

        # 按新编号排序（1, 2, 3, ...），即物理位置从右到左
        columns.sort(key=lambda c: c["index"])
