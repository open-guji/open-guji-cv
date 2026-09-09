# -*- coding: utf-8 -*-
"""控制台 · 夹注段卡。

一段雙行小注一张卡

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

from fastapi import APIRouter

from .. import deps
from ...review.jiazhu_cards import jiazhu_segments

router = APIRouter()



@router.get("/api/jiazhu/segments")
def api_jiazhu_segments(book: str = "vol02", pages: str = "jz",
                        only: str = "all", batch: str | None = None) -> dict:
    """夹注**段**卡：一张卡 = 一段雙行小注，不是一格一张。装配在 `review/jiazhu_cards.py`。

    一段版本注 5–19 字，人一眼能读整句；逐格出卡等于把一句话拆成十几道题。
    `only`：all（默认）| review 只出含待审格的段 | auto 只出全自动的段（抽查用）。
    """
    return jiazhu_segments(book, pages, only, batch,
                           deps.product_store(), deps.event_log())
