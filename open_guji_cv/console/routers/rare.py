# -*- coding: utf-8 -*-
"""控制台 · 生僻字面板。

单查 / 批量（引擎在 clustering/rare_panel.py）

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from .. import deps
from ..auth import require_reviewer
from ..errors import maps_http
from open_guji_cv.console_api import font_index_status, ids_fallback, rare_batch, rare_for, rare_patch
from open_guji_cv.console_api import ImageMissing

router = APIRouter(dependencies=[Depends(require_reviewer)])


@router.get("/api/rare/status")
def api_rare_status() -> dict:
    """字体候选索引现在能不能用（任务书-K-控制台常驻内存，2026-09-28）。

    `deferred=True`：磁盘上还缺字体索引，且此刻有活跑批，冷建被推迟了——
    这段时间字体候选（HOG 那一路）不可用，前端可以照这个字段提示
    「字体候选暂不可用」。库/CNN 两路候选不受影响，正常返回。
    """
    return font_index_status()


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
    # 字表按这册书的整理本算，不写死刻本链那份（2026-09-15，见 rare_panel.rare_batch）
    from open_guji_cv.console_api import book_corpus
    return {"id": f"{book}:{page}:{col}:{slot}{sub or ''}",
            "candidates": rare_for(img, k, book_corpus(book), book)}



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


@router.get("/api/rare/alt/{book}/{page}/{col}/{slot}")
@maps_http
def api_rare_alt(book: str, page: int, col: int, slot: int, sub: str = "",
                 p: list[str] = Query(default=[]), q: str = "", k: int = 30) -> dict:
    """**相似字（以字找字）**：近似字的异体族（hanzi 库＋本机字统网缓存）按这格字块图排序。

    用户 10-19：人审最花时间的是先认出一个近似字、再去字统网翻它的异体、挑和图最像的。
    `p`＝卡上已有的近似字（整理本字、上下文字、库前几名，前端从卡上取），字统网只读缓存；
    `q`＝人键入的近似字，缓存里没有就去字统网取一次（约 2.5 秒，取到写缓存）。
    出待审单时同一函数批量算好写进 pending（`guji audit alt`），网站只显示；控制台在这里现算。
    引擎 `review/alt_cands.py`；只出候选、不进放行。"""
    from open_guji_cv.console_api import shared_zi
    from open_guji_cv.console_api import alt_for_image, pivots_of
    img = rare_patch(book, page, col, slot, sub, deps.image_cache())
    if img is None:
        raise ImageMissing(f"没有字块 p{page:04d}c{col:02d}s{slot}{sub or ''}")
    zi = shared_zi()
    typed = [c for c in q if not c.isspace()][:1]
    if typed:
        zi.ensure(typed[0])                  # 只为人键入的那个字联网，取到写缓存
    piv = typed + pivots_of({}, [c for c in p if len(c) == 1])
    return {"id": f"{book}:{page}:{col}:{slot}{sub or ''}", "pivots": piv,
            "candidates": alt_for_image(book, img, piv, k=k, zi=zi)}


@router.get("/api/rare/search/{book}")
@maps_http
def api_rare_ids_search(book: str, top: str = "", slot: list[str] = Query(default=[]),
                        comp: list[str] = Query(default=[]), page: int = 0, col: int = 0,
                        cell: int = 0, sub: str = "", k: int = 10) -> dict:
    """**IDS 兜底**（2026-09-21，M0）：候选全错时按结构 + 认出的部件查字。

    `?top=⿰&slot=L=言&comp=俞`，给了 `page/col/cell` 就拿那个字块的 emb 在
    取回的字集里排序。引擎 `rare_panel.ids_fallback`；只出候选。
    """
    slots = dict(x.split("=", 1) for x in (slot or []) if "=" in x)
    img = rare_patch(book, page, col, cell, sub, deps.image_cache()) if page else None
    return {"book": book, "query": {"top": top, "slots": slots, "components": comp or []},
            "with_image": img is not None,
            "candidates": ids_fallback(top or None, slots, comp or [], img, k, book)}
