# -*- coding: utf-8 -*-
"""控制台 · 生僻字面板。

单查 / 批量（引擎在 clustering/rare_panel.py）

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .. import deps
from ..errors import maps_http
from ...clustering.rare_panel import rare_batch, rare_for, rare_patch
from ...errors import ImageMissing

router = APIRouter()



@router.get("/api/rare/{book}/{page}/{col}/{slot}")
@maps_http
def api_rare_candidates(book: str, page: int, col: int, slot: int,
                        sub: str = "", k: int = 10) -> dict:
    """**生僻字面板**：字体模板 top-k 候选 + 每个候选的 IDS / 频次 / 码点。

    用户的原话：「碰到生僻字，我需要去字统网查阅是否有一致的 unicode 已收字，
    如果没有完全一致的，找最像的，还要看意思是否合适，查词典。」

    这一步要消掉的就是那趟外链之旅。库/OCR/上下文三路都给不出答案时
    （rare-char 集上那 14 条），字体模板 top-10 召回 **78.6%**、命中时中位
    名次 1——人在候选里点一下即可。每个候选带：

    - **IDS 拆字**（⿰言俞 vs ⿰言侖）：对着图一眼就能比结构；
    - **本书频次**：整理本里出现过几次，0 次的多半是异体或刻本特有字；
    - **码点**：要不要造字、是不是扩展区字，看一眼就知道；
    - **zi.tools 深链**：只链接不抓取（该站无授权条款，见
      glyph_db_expansion_research §1）。

    字体候选是**纯形状**证据，没有文本兜底，所以只出候选、永不放行。
    """
    import cv2

    from ...clustering.font_candidates import book_charset, candidates
    from ...clustering.ids_guard import ids_of
    from ...clustering.normalize import normalize_patch
    from ...products.cache import ImageCache
    from ...steps.align_ref import DEFAULT_CORPUS

    img = rare_patch(book, page, col, slot, sub, deps.image_cache())
    if img is None:
        raise ImageMissing(f"没有字块 p{page:04d}c{col:02d}s{slot}{sub or ''}")
    # ── 两档字表：小表定名次，大表保召回 ──────────────────
    #
    # 字表不能只取整理本用字：**最生僻的字恰恰是整理本里没有的那些**
    # ——刻本刻「㕔」而整理本作「廳」、刻「䙝」而整理本作「褻」，整理本里
    # 频次都是 0，只用整理本字表永远召不回来（实测 㕔 从名次 1 掉到榜外）。
    #
    # 但直接并上异体展开（4636 → 20059 字）会把名次冲垮：多出来的一万五千
    # 个字大多是本书不会出现的罕用形，它们在 HOG 上与正确答案难分伯仲，
    # 于是**top-1 从 43% 掉到 29%**（rare-char 21 条实测）。用户反馈的
    # 「点生僻字查询准确率不高」就是这个。
    #
    # 试过三条都不行，记下来免得重走：
    #   本书频次加权   top3 67% → 33%（要找的字本来就罕见，频次先验反着起作用）
    #   异体身份加权   top3 67% → 62%
    #   相似度闸控扩表 从不触发（小表 top1 分数恒 >0.84，错的时候也高）
    #
    # 有效的是**位次合并**：小表 top3 占据前三名（那里最可能是对的），
    # 其后接大表结果补召回。实测 top1 43% / top10 76%，两头都拿到。
    return {"id": f"{book}:{page}:{col}:{slot}{sub or ''}",
            "candidates": rare_for(img, k)}



class RareBatchIn(BaseModel):
    """一次问一批字位的生僻字候选。"""
    book: str
    slots: list[str]        # ["71:1:5", "71:2:3a", ...]（page:col:slot[a|b]）
    k: int = 3



@router.post("/api/rare/batch")
def api_rare_batch(req: RareBatchIn) -> dict:
    """**批量版**（2026-09-07）：一次问一批字位，字表与 CNN 索引只热一次。

    引擎在 `clustering/rare_panel.py`（C2 搬出去的）。实测一页（约 30 个待审位）
    从 ~10s 降到 ~2s。
    """
    return rare_batch(req.book, req.slots, req.k, deps.image_cache())
