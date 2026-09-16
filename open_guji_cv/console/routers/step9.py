# -*- coding: utf-8 -*-
"""控制台 · Step9 结果整理（9.1 坐标转字符位、9.2 可阅读排版）。

设计见 `overview` 仓 `项目进展/图片初步数字化/进度/Step9-结果整理/
01-结果排版.md`（9.1）与 `03-可阅读排版.md`（9.2）。渲染逻辑分别在
`render/guji_markdown.py`、`render/reading_layout.py`；本路由只做
「解析参数 → 调用 → 返回」。

**不进管线**：Step9 不注册进 `core.step.STEPS`，这两个接口也不挂在任何
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
from ...render.reading_layout import DEFAULT_BASELINE_KG, reflow_page_structured

router = APIRouter()


@router.get("/api/step9/render/{book}")
@maps_http
def api_step9_render(book: str, pages: str) -> dict:
    """9.1：把 `pages`（`book.resolve_pages` 支持的表达式，如 `"33"`、
    `"10,33,89"`、`"33-40"`）逐页拼成 guji-markdown 文本。

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


@router.get("/api/step9/reflow/{book}")
@maps_http
def api_step9_reflow(book: str, pages: str, baseline_kg: int = DEFAULT_BASELINE_KG) -> dict:
    """9.2：先跑一遍 9.1（`render_page`），再把每页转成可阅读排版的
    结构化段落列表——每段带 `is_title`（是否按"孤立单行"规则识别成
    标题），供前端高亮，不用从拼好的字符串或 notes 文本里正则反推。

    `baseline_kg`：这一批页面的正常行挪抬点数（已知常量，默认2）。
    **基线按页independent 传入同一个值，不跨页自动延续**——`vol02`
    实测"謹按"引导的基线切换确实跨页持续过（p10→p11），但那是同一次
    `reflow_page_structured` 调用内部的状态；本接口对每一页各自独立
    调用一次（内部找不到"上一页处理完的基线是多少"这个状态），跨页
    延续的场景以后有需要再补，现在如实说明，不假装做到了。
    """
    bk = load_book(book)
    page_list = bk.resolve_pages(pages)
    store = deps.product_store()

    stale: list[str] = []
    pages_out: list[dict] = []
    for page in page_list:
        page_stale: list[str] = []
        text = render_page(store, book, page, page_stale)
        stale.extend(page_stale)
        notes: list[str] = []
        paragraphs = reflow_page_structured(store, book, page, text, baseline_kg, notes)
        pages_out.append({
            "page": page,
            "paragraphs": [{"text": p.text, "is_title": p.is_title} for p in paragraphs],
            "notes": notes,
        })

    return {"pages": pages_out, "stale": stale}
