# -*- coding: utf-8 -*-
"""`border_class` 打回路由（2026-09-27）：核实过前端全部卡片 id 形态后接上——

`border_class` 只有两种真实/代码列级形态（`colborder:`、无前缀 `book:page:col`），
`headcol:`/`outer:` 两种前缀核实后**不是** `border_class`（分别是 `head_raise`/
`verdict`），见 `feedback/border_class_route.py` 模块头的表。路由只标记过期
（`product_invalidate`），不起跑批，同 `cutline`/`n_body_slots` 已有的做法。
"""
from __future__ import annotations

from open_guji_cv.feedback.events import EventTarget, make_event
from open_guji_cv.feedback.routes import RouteTable


# ── parse_border_class_key：覆盖每种 id 形态 ─────────────────────────────


# ── is_defect_answer：两种 payload 形状都要认 ────────────────────────────


# ── 路由：只在 glued/none 时标记过期，clean/idk 不触发 ───────────────────

def _colreview_event(book, page, col, top_class, bot_class, seq=1):
    key = f"{book}:{page}:{col}"
    return make_event(f"{book}-column", seq, "border_class",
                      EventTarget(step="column_warp", unit="column", key=key,
                                  book=book, page=page, col=col),
                      {"top_class": top_class, "bot_class": bot_class,
                       "border_class": f"top={top_class},bot={bot_class}"})


def _colborder_event(book, page, col, end, answer, seq=1):
    key = f"colborder:{book}:{page}:{col}:{end}"
    return make_event(f"{book}-colborder-review", seq, "border_class",
                      EventTarget(step="column_warp", unit="column", key=key,
                                  book=book, page=page, col=col),
                      {"border_class": answer, "question": "column_warp.page.border_class"})


def test_column_review_panel_glued_routes_to_product_invalidate_column_warp():
    e = _colreview_event("bxgb", 38, 14, "glued", "clean")
    dests = RouteTable.load(None).destinations(e)
    inv = [d for d in dests if d.consumer == "product_invalidate"]
    assert inv and inv[0].extra == {"step": "column_warp"}
    # gold_add 那条既有路由不受影响，两个消费者都要收到
    assert any(d.consumer == "gold_add" and d.shard == "char-segmentation/column-warp" for d in dests)


def test_column_review_panel_none_bottom_routes_to_product_invalidate():
    e = _colreview_event("bxgb", 8, 6, "clean", "none")
    dests = RouteTable.load(None).destinations(e)
    inv = [d for d in dests if d.consumer == "product_invalidate"]
    assert inv and inv[0].extra == {"step": "column_warp"}


def test_column_review_panel_clean_does_not_invalidate():
    e = _colreview_event("bxgb", 1, 1, "clean", "clean")
    dests = RouteTable.load(None).destinations(e)
    assert not [d for d in dests if d.consumer == "product_invalidate"]


def test_column_review_panel_idk_does_not_invalidate():
    """idk 是「拿不准」，不是「改判有问题」，不该标过期——同 cutline 只在
    verdict∈(overlap,idk) 里排除 idk 没有类比意义？不，cutline 反而是 idk 也退回；
    这里对齐 13 §二·3 字面「glued/none」，不含 idk。"""
    e = _colreview_event("bxgb", 1, 1, "idk", "clean")
    dests = RouteTable.load(None).destinations(e)
    assert not [d for d in dests if d.consumer == "product_invalidate"]


def test_colborder_glued_routes_to_product_invalidate_column_warp():
    e = _colborder_event("vol01", 47, 2, "top", "glued")
    dests = RouteTable.load(None).destinations(e)
    inv = [d for d in dests if d.consumer == "product_invalidate"]
    assert inv and inv[0].extra == {"step": "column_warp"}


def test_colborder_clean_does_not_invalidate():
    e = _colborder_event("vol01", 47, 2, "bot", "clean")
    dests = RouteTable.load(None).destinations(e)
    assert not [d for d in dests if d.consumer == "product_invalidate"]


def test_page_level_border_class_routes_to_border_detect():
    """13 原表设想的页级分支：前端目前不会产生这种事件（见模块头核实表），
    但规则已按设计补全——`target.unit == "page"` 一出现就该退 `border_detect`。"""
    e = make_event("vol01-page-border", 1, "border_class",
                   EventTarget(step="border_detect", unit="page", key="vol01:47",
                               book="vol01", page=47),
                   {"border_class": "glued"})
    dests = RouteTable.load(None).destinations(e)
    inv = [d for d in dests if d.consumer == "product_invalidate"]
    assert inv and inv[0].extra == {"step": "border_detect"}


def test_page_level_border_class_clean_does_not_invalidate():
    e = make_event("vol01-page-border", 1, "border_class",
                   EventTarget(step="border_detect", unit="page", key="vol01:47",
                               book="vol01", page=47),
                   {"border_class": "clean"})
    dests = RouteTable.load(None).destinations(e)
    assert not [d for d in dests if d.consumer == "product_invalidate"]
