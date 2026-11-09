"""雙行小注逐步切（`row_segment.jiazhu_step_split`）的缺省实现：殿本两行逐字对齐，什么都不做。

史記文淵閣本的实现在 `books/shiji_wyg/jiazhu_step.py`（`core/seg_set.OVERRIDES` 登记），开关只对史記开。
"""
from __future__ import annotations


def page_note_runs(dz_dir, pins_file, book: str, page: int):
    """这一页各列整理本的夹注段分法；缺省不认，返回 None。"""
    return None


def apply(res, col_gray, content_x, period, specs, ink_threshold: int = 128, reading_order=None):
    """缺省原样返回。"""
    return res, []
