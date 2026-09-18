# -*- coding: utf-8 -*-
"""Step3 逐列字数人裁：`n_body_slots` 的页级常量在少数列上不成立时的兜底。

## 为什么要有这个

`chars_per_line`（`book.yaml`）是全书版式常量，DP 按它硬切每一列。绝大多数列
是对的，但偶尔真有一列比常量多刻/少刻了一个字——bxgb p33c19 实测：`n_body_slots`
=21，这一列实际 22 字，DP 把多出的那个字压进末格（slot21 装了"宴、白、琳"三个
字，逐格裁图核对确认，见 [[feedback_cell_height_not_merge_signal]]）。

**格高/period 比值判不出这种挤压**——全书测过 8 个"末格偏高"样本，个个是
单字偏高（假阳性），而真正挤压的那格比值反而更低。目前没有可靠的几何信号能
自动探测，所以这一轮先做**人工核对**：出卡、人数、写回、驱动重切。

## 出卡范围

**全部列**（用户 2026-09-18 定：格高比值不可靠，不设"疑似"筛子，避免重蹈
`n_raised_hint` 那种"权威判据"其实是假阳性源的坑）。前端按页筛、按"已裁"筛，
人自己决定查哪些页——参考 [[feedback_step56_only]] 的纪律，把探测范围的判断
交还给人比交给一个不可靠的自动信号更诚实。

## 裁决怎么用

一张卡一个数字：**这一列实际有几个字**（含首尾，不含夹注/空白格）。跟页级
`chars_per_line` 不同就落一条 `kind="n_body_slots"` 事件，回流路径完全比照
`touching-cuts`（[[feedback_anchor_backfill_needed]] 记录过的那条链路）：
写金标 → `product_invalidate` 显式失效该页 `row_segment` → 下次重跑
`feedback/lookup.resolved_slots()` 读回来，覆盖 `effective_body_slots` 算出的
`n_body_col`。

与 `n_raised` 的关系：**不是一回事**。`n_raised` 是抬头多出的格（在版框线
以上，DP 已经有机制处理，见 `column_gate.py` 的 `n_raised_hint`）；这里的
`n_body_slots` 覆盖是版式内的字数（普通格数比常量多/少），DP 目前完全没有
这个自由度，只能靠人给。
"""
from __future__ import annotations

import cv2
import numpy as np

from ..core.spec import column_key, page_key
from ..products.cache import ImageCache
from ..products.store import ProductStore

CARD_KIND = "slot-count"


def slot_count_cards(store: ProductStore, book: str, pages: list[int]) -> list[dict]:
    """逐列出卡：书口/边框外页边列（`line_index` 标非 body 的）不出——
    版心列没有"这列几个字"这个概念，见 [[project_keben_column_types]]。
    跳过闸1判 skip 的页（封面等），理由同 `column_review.py`。
    """
    out: list[dict] = []
    for pg in pages:
        try:
            gate = store.read(book, "border_detect_gate", page_key(pg),
                              "border_detect_gate_manifest")
            if getattr(gate, "page_type_policy", "") == "skip":
                continue
        except Exception:                                    # noqa: BLE001
            pass
        try:
            wins = store.read(book, "column_warp", page_key(pg), "column_windows")
        except Exception:                                    # noqa: BLE001
            continue
        skip_cols: set[int] = set()
        try:
            li = store.read(book, "border_detect", page_key(pg), "line_index")
            skip_cols = {i for i, ln in enumerate(li.lines, 1)
                         if getattr(ln, "kind", "body") != "body"}
        except Exception:                                    # noqa: BLE001
            pass
        try:
            cells = store.read(book, "row_segment", page_key(pg), "cells")
            ccols = {c.col: c for c in cells.columns}
        except Exception:                                    # noqa: BLE001
            ccols = {}
        for w in wins.columns:
            if w.col in skip_cols:
                continue
            cc = ccols.get(w.col)
            det_n = None if cc is None else len(cc.cells)
            det_ok = None if cc is None else bool(cc.ok)
            out.append(dict(
                id=f"{book}:{pg}:{w.col}", kind=CARD_KIND,
                book=book, page=pg, col=w.col,
                det_n_slots=det_n, det_ok=det_ok,
                img=f"/api/slot-count-review/img/{book}/{pg}/{w.col}.png"))
    return out


def render_slot_count_img(book: str, page: int, col: int, *, image_cache: ImageCache,
                          store: ProductStore) -> np.ndarray:
    """整列图 + 现有切分线（红），给人逐格数字数用。

    与 `column_review.py` 的 img 端点画的是**不同的线**——那边画 Step2 的
    band/trim（左右带、上下削行），这里画 Step3 的**格线**（`cells` 的
    `y0`），人要数的是格数，不是带宽。
    """
    p = image_cache.get(book, "column_raw", column_key(page, col))
    if p is None:
        raise FileNotFoundError(f"没有这一列的矫正图：{book}/{page}/{col}")
    g = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
    if g is None:
        raise FileNotFoundError(f"列图读不出来：{book}/{page}/{col}")
    im = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    h, w = im.shape[:2]
    try:
        cells = store.read(book, "row_segment", page_key(page), "cells")
        cc = next((c for c in cells.columns if c.col == col), None)
    except Exception:                                        # noqa: BLE001
        cc = None
    if cc is not None:
        for cell in cc.cells:
            y = int(round(cell.y0))
            if 0 <= y < h:
                cv2.line(im, (0, y), (w - 1, y), (0, 0, 220), 1)
        if cc.cells:
            y = int(round(cc.cells[-1].y1))
            if 0 <= y < h:
                cv2.line(im, (0, y), (w - 1, y), (0, 0, 220), 1)
    return im
