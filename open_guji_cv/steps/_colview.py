"""列窗口的「合并视图」：把 2a `column_windows`、2b `column_bands`、2c `column_ends` 按列拼成一份 `PageWindows`。

五小步拆分（2026-11-25）后刻本链的列级量分在三个产物里；读 `band`／`trim_*`／`triage`／`frame_residue_*` 的下游
（交接闸、`cell_shrink`）经这里取，字段名与拆分前一致。没有 2b／2c 产物时（现代印刷链的 `column_crop` 自己写满）
原样返回 `column_windows`。
"""

from __future__ import annotations

from ..core.step import RunContext
from ..products.kinds.columns import PageWindows


def merged_windows(ctx: RunContext, page: int) -> PageWindows:
    wins: PageWindows = ctx.product("column_windows", page)
    if not wins.columns or not ctx.has_product("column_bands", page) or not ctx.has_product("column_ends", page):
        return wins
    bands, ends = ctx.product("column_bands", page), ctx.product("column_ends", page)
    cols = []
    for c in wins.columns:
        b, e = bands.column(c.col), ends.column(c.col)
        if b is None or e is None:
            cols.append(c)
            continue
        cols.append(c.model_copy(update={
            "band": b.band, "trim_top": e.trim_top, "trim_bottom": e.trim_bottom, "triage": e.triage,
            "frame_residue_top": e.frame_residue_top, "frame_residue_bottom": e.frame_residue_bottom}))
    return wins.model_copy(update={"columns": cols})
