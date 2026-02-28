"""列结构分析器 —— 在边框检测基础上精确分析列宽一致性。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ..profile import BookProfile


class ColumnDetector:
    """列结构精细分析。

    在 BorderDetector 检测到的列间界栏基础上：
    1. 验证列宽一致性
    2. 修正异常的界栏位置
    3. 补充缺失的界栏
    """

    def analyze(self, border_result: dict,
                profile: BookProfile | None = None) -> dict:
        """分析列结构。

        Args:
            border_result: BorderDetector 的输出
            profile: 可选的 BookProfile

        Returns:
            {
                "columns": [...],  # 精化后的列信息
                "column_width_stats": {
                    "mean": float,
                    "std": float,
                    "cv": float,  # 变异系数
                },
                "is_uniform": bool,  # 列宽是否一致
            }
        """
        columns = border_result.get("columns", [])
        if not columns:
            return {
                "columns": [],
                "column_width_stats": {"mean": 0, "std": 0, "cv": 0},
                "is_uniform": False,
            }

        widths = [col["width"] for col in columns]
        mean_w = np.mean(widths)
        std_w = np.std(widths)
        cv = std_w / mean_w if mean_w > 0 else 0

        # 列宽变异系数 < 0.15 认为是均匀的
        is_uniform = bool(cv < 0.15)

        result = {
            "columns": columns,
            "column_width_stats": {
                "mean": float(mean_w),
                "std": float(std_w),
                "cv": float(cv),
            },
            "is_uniform": is_uniform,
        }

        # 如果有先验知识，尝试修正
        if profile is not None and not is_uniform:
            corrected = self._try_correct_columns(
                columns, profile.lines_per_page, border_result)
            if corrected is not None:
                result["columns_corrected"] = corrected

        return result

    def _try_correct_columns(self, columns: list[dict],
                             expected_count: int,
                             border_result: dict) -> list[dict] | None:
        """尝试根据先验行数修正列结构。

        如果检测到的列数与预期不符，尝试：
        1. 如果少了：在异常宽的列中间插入界栏
        2. 如果多了：合并异常窄的相邻列
        """
        detected = len(columns)

        if detected == expected_count:
            return None

        inner_left = border_result.get("inner_frame", {}).get("left", {}).get("intercept", 0)
        inner_right = border_result.get("inner_frame", {}).get("right", {}).get("intercept", 0)

        if inner_right <= inner_left:
            return None

        total_width = inner_right - inner_left
        expected_col_width = total_width / expected_count

        if detected < expected_count:
            # 列太少：在异常宽的列中均匀拆分
            corrected = []
            idx = 0
            for col in columns:
                if col["width"] > expected_col_width * 1.5:
                    # 计算应该拆成几列
                    n_splits = round(col["width"] / expected_col_width)
                    split_width = col["width"] / n_splits
                    for j in range(n_splits):
                        corrected.append({
                            "index": idx,
                            "left_x": col["left_x"] + j * split_width,
                            "right_x": col["left_x"] + (j + 1) * split_width,
                            "width": split_width,
                        })
                        idx += 1
                else:
                    corrected.append({**col, "index": idx})
                    idx += 1
            return corrected

        return None
