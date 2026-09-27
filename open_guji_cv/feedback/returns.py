# -*- coding: utf-8 -*-
"""打回：一个单元的上游处理被判定有问题，该退回哪一步重做（2026-09-27）。

总览/13（打回台账，独立设计，从未落代码）并入总览/15（绑定表）——对照见
overview `进度/总览/17-13并入15-字段对照.md`。**不是**再造一张独立台账：打回
就是绑定行上的三个新字段（`return_to`／`return_reason`／`return_status`），
跟 `status`（valid/rebound/review/void/unanchored，答的是「这条裁决还对不对
得上格」）**是两件事、两列**，别混进同一列——这三个字段答的是「这一格的上游
处理有没有问题、该退给谁、退回工单办完了没」。都是从事件现算，不单独开文件、
不设独立主键，跟 `bindings.py` 的其余部分同一套架构（读全部相关事件、按时间
取最新、可重算）。

## 13 §二·3 路由表，本轮实现到哪

只接了**能从单条事件直接判定、不需要额外上下文**的三类：

| 事件 | 触发条件 | to_step | reason |
|---|---|---|---|
| `confirm v=seg_defect` | quality=contaminated | `row_segment` | `seg_noise` |
| `confirm v=seg_defect` | quality=truncated | `row_segment` | `seg_truncated` |
| `confirm v=seg_defect` | defect 以 `jiazhu_` 开头 | `row_segment` | `jiazhu_split` |（⚠️ 现在
  `collate_state.SEG_FLAGS` 只有 `truncated`／`contaminated` 两档，没有 `jiazhu_*`——这条按 13
  原表先写上，眼下不会触发，等夹注面板真的产出这种 payload 再验证）
| `cutline` | verdict∈(overlap, idk) | `row_segment` | `cut_unresolvable` |
| `n_body_slots` | 任意（人裁即代表现有 slot 数与人看到的不符） | `row_segment` | `slot_count` |

**没接的两类，留到下一轮**：
- `seg_truncated` 13 原表按首/末格分流到 `cell_shrink`／`row_segment`——这里先统一到
  `row_segment`（该步能处理三种情况），首末格细分需要列内位置，单条事件判不出，下一轮
  如果要细分再加。
- `border_class`（边框裁决）：13 说退 `border_detect`/`column_warp`，但 `border_class`
  这个 kind 在前端有**四种不同的卡片 id 约定**（`colborder:`/`outer:`/`headcol:`/
  `column_warp.page.border_class` 页级），没有逐一对着代码核实清楚 id 与「列级 vs
  页级」的对应关系之前，宁可不接也不要接错——接错等于把打回挂到错的列/页上，比
  不接更糟。列在 `ask` 单里，交下一轮或协调者判断。

## 单元展开（列级事件 → 一组格级绑定行）

`cutline`／`n_body_slots` 都是 `unit="column"`，落到绑定表要展开成受影响的格：

- `cutline`：只影响这条线**上下两格**——事件自带 `payload.slot_above`/`slot_below`，
  不用查产物；
- `n_body_slots`：人说「这一列实际字数不对」，影响**这一列全部格**——需要当前列的
  格索引（复用 `bindings.py` 已有的 `_cell_index`）。

## `return_resolve`：结案

人在本步待办卡上点「已修」/「不是问题」，写一条 `return_resolve` 事件，`target.key`
与触发它的原打回**同一个格键**。取「同一格键的全部打回相关事件里最新一条」定
`return_status`：没有 `return_resolve` 或原触发之后没有更新的 → `open`；
`return_resolve` 更晚且 `resolution=fixed` → `fixed`；`=wontfix` → `wontfix`。
"""

from __future__ import annotations

from .events import Event

#: reason → 退回哪一步。13 §二·3 的路由表，本轮实现的子集（见模块头）。
REASON_TO_STEP: dict[str, str] = {
    "seg_noise": "row_segment",
    "seg_truncated": "row_segment",
    "jiazhu_split": "row_segment",
    "cut_unresolvable": "row_segment",
    "slot_count": "row_segment",
}


def classify_return(e: Event) -> tuple[str, str] | None:
    """事件 → `(to_step, reason)`；不是打回触发事件就返回 `None`。"""
    p = e.payload or {}
    if e.kind == "confirm" and p.get("v") == "seg_defect":
        defect = p.get("defect") or ""
        if defect.startswith("jiazhu_"):
            return REASON_TO_STEP["jiazhu_split"], "jiazhu_split"
        q = p.get("quality")
        if q == "contaminated":
            return REASON_TO_STEP["seg_noise"], "seg_noise"
        if q == "truncated":
            return REASON_TO_STEP["seg_truncated"], "seg_truncated"
        return None
    if e.kind == "cutline" and p.get("verdict") in ("overlap", "idk"):
        return REASON_TO_STEP["cut_unresolvable"], "cut_unresolvable"
    if e.kind == "n_body_slots":
        return REASON_TO_STEP["slot_count"], "slot_count"
    return None


def affected_slots(e: Event, cur_idx: dict) -> list[tuple[int, int, str]]:
    """打回事件 → 受影响的 `(col, slot, sub)` 列表（对着 `cur_idx`——`_cell_index()`
    的返回值——展开；返回的都是**当前确实存在**的格，格已经不在了就不会出现）。

    `confirm`（cell 级）不必展开，调用方直接按事件自己的 `(col, slot, sub)` 用，
    不必也不该走这里——这里只处理 `cutline`/`n_body_slots` 两种列级事件。
    """
    if e.kind == "cutline":
        col = e.target.col
        if col is None:
            return []
        p = e.payload or {}
        out = []
        for k in ("slot_above", "slot_below"):
            s = p.get(k)
            if s is None:
                continue
            for sub in ("", "a", "b"):
                if (col, s, sub) in cur_idx:
                    out.append((col, s, sub))
        return out
    if e.kind == "n_body_slots":
        col = e.target.col
        if col is None:
            return []
        return [(c, s, sub) for (c, s, sub) in cur_idx if c == col]
    return []


def resolve_status(key_events: list[Event]) -> str:
    """同一格键的打回相关事件（触发 + `return_resolve`），按时间取最新，定
    `return_status`。`key_events` 必须已经按 `(ts, batch, seq)` 升序。"""
    status = "open"
    for e in key_events:
        if e.kind == "return_resolve":
            r = (e.payload or {}).get("resolution")
            if r in ("fixed", "wontfix"):
                status = r
        elif classify_return(e) is not None:
            status = "open"      # 新一轮打回触发，覆盖掉之前的结案状态
    return status
