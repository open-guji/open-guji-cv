# -*- coding: utf-8 -*-
"""控制台 · Step9 结果整理（坐标转字符位）。

设计见 `overview` 仓 `项目进展/图片初步数字化/进度/Step9-结果整理/01-结果排版.md`。
渲染逻辑在 `render/guji_markdown.py`；本路由只做「解析参数 → 调用 → 返回」。

**不进管线**：Step9 不注册进 `core.step.STEPS`，这个接口也不挂在任何
`runs`/队列上——用户 2026-09-11 明确要求「审阅完了再一起做整册」是常态，
但也要「允许审阅一半时直接输出看看效果」，所以这里是**现场调用**，不落盘、
不排队，随时点随时跑，跑多久是多久（页数别选太大，没有进度条）。
"""
from __future__ import annotations

from fastapi import APIRouter

from .. import deps
from ..errors import maps_http
from ...core.book import load_book
from ...render.guji_markdown import render_page

router = APIRouter()


@router.get("/api/step9/render/{book}")
@maps_http
def api_step9_render(book: str, pages: str) -> dict:
    """把 `pages`（`book.resolve_pages` 支持的表达式，如 `"33"`、`"10,33,89"`、
    `"33-40"`）逐页拼成 guji-markdown 文本。

    某一页缺产物（Step3/Step7 没跑到）会让整批请求失败——**不是**跳过那一页
    继续拼其余页。理由：这本来就是「看几页效果」的交互式调用，页数不多，
    失败了直接告诉用户哪页缺什么、去补哪一步，比悄悄漏一页更清楚。
    """
    bk = load_book(book)
    page_list = bk.resolve_pages(pages)
    store = deps.product_store()

    stale: list[str] = []
    parts: list[str] = []
    for page in page_list:
        parts.append(f"#第{page}页")
        parts.append(render_page(store, book, page, stale))

    return {"text": "\n".join(parts), "pages": page_list, "stale": stale}
