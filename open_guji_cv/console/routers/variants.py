# -*- coding: utf-8 -*-
"""控制台 · 异体用字。

本书用字账（只读）/ 组视图

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

from fastapi import APIRouter

from .. import deps
from ..errors import maps_http
from ...errors import NotFound
from ...review.group_view import group_view

router = APIRouter()



@router.get("/api/variants/book")
@maps_http
def api_variants_book(edition: str = "") -> dict:
    """本书用字账（只读）：`config/variants/books/<edition>.json` 原样返回。

    账本由 `scripts/build_book_variants.py` 从产物 + glyph.db + 整理本语料派生，
    这里不算任何东西——控制台只是把「这本书用哪个异体」摆出来看
    （variant_strategy.md §3.2；`variant_ledger.py` 有字段说明）。
    """
    import json

    from ...variant_ledger import DEFAULT_EDITION, ledger_path

    ed = edition or DEFAULT_EDITION
    p = ledger_path(ed)
    if not p.exists():
        raise NotFound(
            f"没有用字账 {p.name}——先跑 python scripts/build_book_variants.py --edition {ed}")
    return json.loads(p.read_text(encoding="utf-8"))



@router.get("/api/variants/groups")
@maps_http
def api_variants_groups(book: str, pages: str = "dev_set", edition: str = "",
                        limit_tiles: int = 400) -> dict:
    """组视图（variant_strategy.md §5.1）：按异体组把字位摊成「列 = 形、格 = 图块」。

    装配在 `review/group_view.py`（C2 搬出去的）——**判据 E 的分母就在那里算**。
    """
    return group_view(book, pages, edition, limit_tiles, deps.product_store())
