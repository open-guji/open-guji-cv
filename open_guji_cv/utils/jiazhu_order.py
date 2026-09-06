# -*- coding: utf-8 -*-
"""夹注读序：把「(slot, sub) 的一列记录」按**阅读顺序**排开。

`row_boundaries.reading_order` 是读序的唯一权威，但它吃的是 Step3 的 `Cell`
对象。下游（`context_decide` / `v2_align` / 审阅页）手上只有带 `slot`/`sub`
两个字段的记录（`MatchRec`/`AdmitRec`/`DecisionRec`），拿不到 `Cell`，此前一律
写成 `sorted(key=(slot, sub))`——那是**错的**：

    slot 17: 兩(a) 採(b)      按 (slot, sub) 排 → 兩 採 淮 進 鹽 本 政
    slot 18: 淮(a) 進(b)      正确读序        → 兩 淮 鹽 政 採 進 本
    slot 19: 鹽(a) 本(b)
    slot 20: 政(a)

前向 n-gram LM 看到交错串必然 margin 不足（2026-09-06 实测：22 条夹注人审里
13 条库 top == OCR top，本该 dual 放行，全被「上下文 margin 不足」拦下）；
`v2_align` 的 8-gram 锚定同样被交错串带偏，连累邻近正文的金标。

这里把 `reading_order` 的规则抽成**只依赖 (slot, sub)** 的排序键，两边共用一条
规则，避免各写一份再漂移。规则本身逐条对应 `reading_order` 的 docstring：

- 正文格按 slot 升序；
- **连续夹注段**（slot 连续、且该 slot 上有 sub 的格）整体插在段位上，
  段内先 a 全部（slot 升序）再 b 全部；
- slot 在抬头/正文交界跳过 0（-1 后面直接是 1），判"相邻"要把这算作相邻。
"""

from __future__ import annotations

from typing import Iterable, Sequence, TypeVar

T = TypeVar("T")


def _adjacent(a: int, b: int) -> bool:
    """slot 跳过 0：-1 与 1 物理相邻。与 `reading_order._adjacent` 同口径。"""
    return b == a + 1 or (a == -1 and b == 1)


def order_keys(pairs: Iterable[tuple[int, str | None]]) -> dict[tuple[int, str], int]:
    """`{(slot, sub or ""): 读序}`。sub 用 `""` 表示正文格（与产物里 `None` 对应）。"""
    subs_at: dict[int, set[str]] = {}
    for slot, sub in pairs:
        subs_at.setdefault(int(slot), set()).add(sub or "")
    slots = sorted(subs_at)
    out: dict[tuple[int, str], int] = {}
    n = 0
    k = 0
    while k < len(slots):
        s = slots[k]
        if any(x for x in subs_at[s]):          # 这一 slot 上有夹注半格
            run = [s]
            while (k + 1 < len(slots) and _adjacent(slots[k], slots[k + 1])
                   and any(x for x in subs_at[slots[k + 1]])):
                k += 1
                run.append(slots[k])
            for sub in ("a", "b"):
                for j in run:
                    if sub in subs_at[j]:
                        out[(j, sub)] = n
                        n += 1
            # 夹注段里混进来的正文格（理论上不该有，防御性处理：排在段末）
            for j in run:
                if "" in subs_at[j]:
                    out[(j, "")] = n
                    n += 1
        else:
            for sub in sorted(subs_at[s]):
                out[(s, sub)] = n
                n += 1
        k += 1
    return out


def sort_by_reading(records: Sequence[T]) -> list[T]:
    """按阅读顺序排一列记录。记录需有 `slot` 与 `sub` 两个属性。

    没有夹注的列，结果与 `sorted(key=slot)` 完全一致——所以正文链路可以无脑换上。
    """
    keys = order_keys((r.slot, getattr(r, "sub", None)) for r in records)  # type: ignore[attr-defined]
    return sorted(records, key=lambda r: keys[(r.slot, getattr(r, "sub", None) or "")])  # type: ignore[attr-defined]


def segments(pairs: Iterable[tuple[int, str | None]]) -> list[list[int]]:
    """连续夹注段 → `[[slot, …], …]`（每段的 slot 升序）。给段级通道与段卡用。"""
    subs_at: dict[int, set[str]] = {}
    for slot, sub in pairs:
        subs_at.setdefault(int(slot), set()).add(sub or "")
    slots = sorted(subs_at)
    runs: list[list[int]] = []
    k = 0
    while k < len(slots):
        if any(x for x in subs_at[slots[k]]):
            run = [slots[k]]
            while (k + 1 < len(slots) and _adjacent(slots[k], slots[k + 1])
                   and any(x for x in subs_at[slots[k + 1]])):
                k += 1
                run.append(slots[k])
            runs.append(run)
        k += 1
    return runs
