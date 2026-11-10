"""雙行小注书级钩子（逐步切 `page_note_runs`／`apply`、两行字数可不等 `free_split`）的缺省实现：殿本两行逐字对齐，什么都不做。

史記文淵閣本的实现在史記书仓 `code/jiazhu_step.py`（`code.yaml` 覆盖 `keben.jiazhu_step`）。2026-11-10 起原书级开关
`row_segment.jiazhu_step_split`、`jiazhu_free_split` 删掉，本模块被覆盖就生效（`row_segment._RETIRED`）。
"""
from __future__ import annotations


def page_note_runs(dz_dir, pins_file, book: str, page: int):
    """这一页各列整理本的夹注段分法；缺省不认，返回 None。"""
    return None


def apply(res, col_gray, content_x, period, specs, ink_threshold: int = 128, reading_order=None):
    """缺省原样返回。"""
    return res, []


#: 雙行小注两行字数可不等（段尾单半）：`(ink_col, n, long_sub, cxi, top, bot, anchor) -> {sub: 格线} | None`，
#: 见 `row_boundaries.segment_column` 的 `free_split`。None＝不用（两行都切 n 格）。
free_split = None
