# -*- coding: utf-8 -*-
"""`border_class` 打回路由：核实卡片 id 形态 + 只标记过期（2026-09-27）。

## 核实结果（任务书 §一）

此前的文档（`feedback/returns.py` 旧版模块头、overview 总览/17 §七）记的是
「`border_class` 在前端有四种不同的卡片 id 约定（`colborder:`/`outer:`/`headcol:`/
`column_warp.page.border_class` 页级）」。逐条对着前端源码核实（`review/border_cards.py`
`console/frontend/src/components/border-review/BorderReviewPanel.tsx`
`console/frontend/src/components/column-review/ColumnReviewPanel.tsx`
`console/frontend/src/components/border-review/HeadRaisePanel.tsx`
`console/frontend/src/types/borderReview.ts` `feedback/questions.py`）后，
其中两种其实**不是** `border_class`：

| id 形态 | 实际 `kind` | 属于哪一级 | 对应产物字段 | 实测事件数（2026-09-27，北行 bxgb + 四庫 vol01/02/03 全部 `feedback/events/*.jsonl`）|
|---|---|---|---|---|
| `{book}:{page}:{col}`（`ColumnReviewPanel`，无前缀，一条事件带 `top_class`+`bot_class`）| `border_class` | **列级**（一条事件覆盖上下两端）| `ColumnTriage.top_class`/`bot_class`（Step2 `column_windows` 产物，`products/kinds/columns.py`）| **31**（全部在 `bxgb-column.jsonl`；四庫 vol01/02/03 目前 0 条）|
| `colborder:{book}:{page}:{col}:{end}`（`end` 是 `top` 或 `bot`；`BorderReviewPanel`，`question=column_warp.page.border_class`）| `border_class` | 列级+端（一条事件一端）| 同上（单端）| **0**（代码路径存在——`review/border_cards.py::colborder_cards`——但从未真正提交过事件）|
| `headcol:{book}:{page}:{col}` | **`head_raise`**，不是 `border_class` | 列级 | `ColumnWindowRec.head_raise_inner_y`/`n_raised` 等 | 与本路由无关，排除（`HeadRaisePanel.tsx` 明文 `kind: 'head_raise'`）|
| `outer:{book}:{page}:{side}` | **`verdict`**，不是 `border_class` | 页级+端 | `BorderResult.top_outer_offset`/`bottom_outer_offset` | 与本路由无关，排除（`border_cards.py` 模块头：「写 `/api/events`（kind=`verdict` 给 cols/head/outer」）；且现有事件日志里 0 条|

结论：**`border_class` 目前只有列级的两种真实/代码形态**，13 §二·3 设想的「页级」分支
在前端还没有任何路径会产生——`BorderReviewPanel.tsx` 与 `ColumnReviewPanel.tsx` 提交
`border_class` 事件时 `unit` 一律是 `'column'`（`BorderReviewPanel` 第 69 行
`unit: kind === 'colborder' ? 'column' : 'page'`——而 colborder 就是唯一会发
`border_class` 的那个 kind；`ColumnReviewPanel` 第 149/152 行也是 `unit: 'column'`）。
下面的路由把页级分支也写上（按 13 的设计补全，不是瞎猜——`target.unit` 是已核实过的
判据），但目前没有真实数据能验证它，等前端真的出现页级 `border_class` 卡时会自动命中。

## 路由做法：只标记过期，不起跑批

同 `cutline`/`n_body_slots`「已有的做法」（见 `feedback/routes.py` 的
`product_invalidate` 消费者）：命中就把该页对应 step 的产物标 `invalidated`，
下次跑批自然重算，这里不主动起跑批。触发条件按 13 §二·3：**`border_class` 答案是
`glued`/`none`**——这本身就代表人给出了跟算法默认判断不一致的结论（同
`cutline` `verdict∈(overlap,idk)` 一样，不需要再去读 Step2 产物比较"改没改判"，
单条事件自己的答案就够）。`clean`/`idk` 不算，跟现状一致，不触发。

两种列级形态的答案可能落在三个不同的 payload 键上，`is_defect_answer()` 都要认：

- `ColumnReviewPanel`：一条事件同时裁两端，答案在 `top_class`/`bot_class`
  （`border_class` 键是给人看的拼接串 `"top=x,bot=y"`，不是原始答案，不能直接比较）；
- `colborder`（`BorderReviewPanel`）：一条事件一端，答案就是 `border_class` 键本身
  （单值，天然不会跟上面的拼接串形态混淆——拼接串不会等于 `"glued"`/`"none"`）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: 册名形态同 `feedback/harvest.py::_BOOK`——字母数字加下划线短横，不含冒号。
_BOOK = r"[A-Za-z][A-Za-z0-9_-]*"
_COLBORDER_RE = re.compile(rf"^colborder:(?P<book>{_BOOK}):(?P<page>\d+):(?P<col>\d+):(?P<end>top|bot)$")
_PLAIN_COLUMN_RE = re.compile(rf"^(?P<book>{_BOOK}):(?P<page>\d+):(?P<col>\d+)$")

#: 13 §二·3 的触发条件：答案是这两档之一才算「人改判、这一格有问题」。
BAD_CLASSES = frozenset({"glued", "none"})


@dataclass(frozen=True)
class BorderClassUnit:
    """`border_class` 卡片 id 解析出来的列级单元。"""

    book: str
    page: int
    col: int
    end: str | None    # None = 一条事件覆盖上下两端（ColumnReviewPanel 形态）


def parse_border_class_key(key: str) -> BorderClassUnit | None:
    """`border_class` 卡片 id → 列级单元。

    **只认核实过的两种列级形态**（模块头的表）；`headcol:`/`outer:` 前缀故意不在
    这里认——它们不是 `border_class` 的 id，认了会把打回挂到错的列/页上。解析不出来
    返回 `None`，调用方应计入「不认识」而不是猜一个结果出来。
    """
    m = _COLBORDER_RE.match(key)
    if m:
        return BorderClassUnit(m["book"], int(m["page"]), int(m["col"]), m["end"])
    m = _PLAIN_COLUMN_RE.match(key)
    if m:
        return BorderClassUnit(m["book"], int(m["page"]), int(m["col"]), None)
    return None


def is_defect_answer(payload: dict) -> bool:
    """这条 `border_class` 事件的答案是不是 `glued`/`none`（见模块头「路由做法」）。"""
    if "top_class" in payload or "bot_class" in payload:
        return payload.get("top_class") in BAD_CLASSES or payload.get("bot_class") in BAD_CLASSES
    return payload.get("border_class") in BAD_CLASSES
