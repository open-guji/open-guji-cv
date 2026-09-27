# -*- coding: utf-8 -*-
"""`parse_card_id`：事件 anchor 的解析（book/page/col/slot）。

2026-09-17 修过一个**静默**故障：册名模式写死成 `vol\\d+|book\\d+`，别的书一律
匹配不上、返回 `{}`，于是事件的 anchor 全空——事件照样落盘、接口照样 200，
只有去翻 jsonl 才看得出来。实测北行日錄刻本 `bxgb` 的 822 条定字裁决 anchor 全空。
"""
import pytest

from open_guji_cv.feedback.harvest import parse_card_id


@pytest.mark.parametrize("cid,want", [
    # 任意册名（不只 vol/book 开头）——这条是 2026-09-17 修的那个坑
    ("bxgb:3:1:21", {"book": "bxgb", "page": 3, "col": 1, "slot": 21}),
    ("bxgb:3:1:21a", {"book": "bxgb", "page": 3, "col": 1, "slot": 21}),
    # 列级 id（书:页:列），Step2 列清理裁决用
    ("bxgb:3:1", {"book": "bxgb", "page": 3, "col": 1}),
    ("bxgb:3", {"book": "bxgb", "page": 3}),
    # 四库那批老形态不能回归
    ("vol01:22:5:4", {"book": "vol01", "page": 22, "col": 5, "slot": 4}),
    ("vol01/50:7:21", {"book": "vol01", "page": 50, "col": 7, "slot": 21}),
    ("colborder:vol01:47:2:top", {"book": "vol01", "page": 47, "col": 2}),
    ("outer:vol01:47:top", {"book": "vol01", "page": 47}),
    ("headcol:vol02:11:4", {"book": "vol02", "page": 11, "col": 4}),
    ("cols:vol02:171", {"book": "vol02", "page": 171}),
    ("vol02:171", {"book": "vol02", "page": 171}),
])
def test_parses(cid, want):
    assert parse_card_id(cid) == want


@pytest.mark.parametrize("cid", ["", "不是id", "bxgb::3", "3:1:21"])
def test_unparseable_returns_empty(cid):
    """认不出就返回 {}，不要瞎猜——猜错的 anchor 比没有 anchor 更难查。"""
    assert parse_card_id(cid) == {}
