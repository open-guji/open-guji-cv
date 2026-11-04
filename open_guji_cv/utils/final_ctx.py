# -*- coding: utf-8 -*-
"""终审取上下文（A24 第 4 轮，2026-11-04）。

终审（大模型只读文意，在候选里选字）要拿到一格前后各 W 字。试点 v1 按格号顺序拼，夹注双行小字被拼乱
（vol20:21:1:15a 应读「古者曰車聲如…今曰車車…」），还有格要跨到下一列才看得懂（vol90:74:9:21）。
这里统一复用管线读序 `utils.jiazhu_order.sort_by_reading`：册内按页序、列序、夹注双行读序展平，跨列、跨页取窗。
不另写读序规则，免得和 context_decide／seed_admit 漂移。

输入是已落盘的产物 dict（`seed_admit` 页产物的 `columns[].chars[]`、`align_ref` 页产物的 `chars[]`），
不依赖 Step 对象，终审脚本、审查页、回放都能直接用。

每个位置取一个字：放行字 → 整理本对位字 → 机器字 → `□`。本格自己不进窗口，也不用本格的放行字
（本格正是要问的）。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Iterable, Mapping

from .jiazhu_order import sort_by_reading

BLANK = "□"


def pick_char(c: Mapping, align: Mapping | None) -> str:
    """一个位置在上下文里取哪个字：放行字 → 整理本对位字 → 机器字 → □。"""
    if c.get("admit") and c.get("char"):
        return c["char"]
    if align and align.get("align_char"):
        return align["align_char"]
    return c.get("char") or BLANK


def flatten(pages: Iterable[tuple[int, Iterable[Mapping]]], align: Mapping[str, Mapping] | None = None
            ) -> list[tuple[str, str]]:
    """把一册展平成读序字流 `[(格 id, 字), …]`。

    `pages`：`(页号, columns)`，columns 每项有 `col` 与 `chars`（每个 char 有 `id/slot/sub/char/admit`）。
    页按页号升序、列按 `col` 升序（右到左已在 col 编号里），列内夹注按 `sort_by_reading`。
    """
    align = align or {}
    stream: list[tuple[str, str]] = []
    for _pg, cols in sorted(pages, key=lambda t: t[0]):
        for col in sorted(cols, key=lambda c: c["col"]):
            recs = [SimpleNamespace(slot=c["slot"], sub=c.get("sub"), raw=c) for c in col.get("chars", [])]
            for r in sort_by_reading(recs):
                c = r.raw
                stream.append((c["id"], pick_char(c, align.get(c["id"]))))
    return stream


def window(stream: list[tuple[str, str]], cell_id: str, w: int = 20, index: Mapping[str, int] | None = None
           ) -> tuple[str, str] | None:
    """`cell_id` 前后各 `w` 字（不含本格）。不在字流里返回 None。跨列、跨页。`index` 可预建 `{id: 位置}` 提速。"""
    if index is None:
        index = {i: n for n, (i, _) in enumerate(stream)}
    n = index.get(cell_id)
    if n is None:
        return None
    left = "".join(t for _, t in stream[max(0, n - w):n])
    right = "".join(t for _, t in stream[n + 1:n + 1 + w])
    return left, right
