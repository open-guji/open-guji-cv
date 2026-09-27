# -*- coding: utf-8 -*-
"""`product_invalidate`：`book`/`page` 空时从 `key` 反解（2026-09-21）。

写入方多半不填这两个字段——bxgb 实测 1,558 条 cell 事件里 822 条（53%）都是 None，
而 `key` 一直是完整的 `<book>:<页>:<列>:<格>`。不兜底的话过半人裁**不触发产物失效**：
裁决进了库、`seed_admit` 不知道、待审列表照旧端出那张卡。

`review/verdict_view.decided_cells` 早就按 key 前缀认书了，这里是补上同一条兜底。
"""
from __future__ import annotations

from open_guji_cv.feedback.consumers import product_invalidate
from open_guji_cv.feedback.events import EventTarget, make_event
from open_guji_cv.feedback.routes import Destination


def _ev(key: str, *, book=None, page=None, seq=1):
    return make_event("b", seq, "confirm",
                      EventTarget(step="seed_admit", unit="cell", key=key,
                                  book=book, page=page),
                      {"v": "confirm", "shape": "別"}, source_format="server")


def _pairs(*evs):
    return [(e, Destination(consumer="product_invalidate", extra={"step": "seed_admit"})) for e in evs]


def test_falls_back_to_key_when_book_page_missing():
    res = product_invalidate(_pairs(_ev("bxgb:10:11:1")), dry_run=True)
    assert res.added == 1 and not res.errors, res.errors


def test_explicit_book_page_still_win():
    res = product_invalidate(_pairs(_ev("bxgb:10:11:1", book="bxgb", page=10)), dry_run=True)
    assert res.added == 1 and not res.errors


def test_same_page_deduped():
    """同一页多条裁决只失效一次。"""
    res = product_invalidate(_pairs(_ev("bxgb:10:11:1", seq=1),
                                    _ev("bxgb:10:11:2", seq=2),
                                    _ev("bxgb:11:1:1", seq=3)), dry_run=True)
    assert res.added == 2, "p10 两条应合成一次，p11 另算一次"


def test_unparseable_key_is_reported_not_silently_dropped():
    res = product_invalidate(_pairs(_ev("garbage")), dry_run=True)
    assert res.added == 0 and res.skipped == 1
    assert "反解不出" in res.errors[0]
