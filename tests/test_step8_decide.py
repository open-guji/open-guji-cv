# -*- coding: utf-8 -*-
"""Step8 复核裁决 → 事件（2026-09-22）。

只测 `_events_for`（裁决组合 → 写哪些事件），不起服务：这段是「点哪个按钮落到哪」
的唯一真相源，落库那头另有 test_collate_consumers 覆盖。

**按字对提交，可展开成 N 格**：`ids` 是这次要裁的字位——「N 处一起裁」勾上是全部，
不勾只一个（用户 2026-09-22：「不勾应该裁两次」）。所以逐格的事件（confirm /
collate_ok）条数要跟着 `ids` 走，而跨书/本书的标签（mark_jiajie / variant_deny /
char_convention）**只记一条**：那是贴给字对的，与字位无关。
"""
from __future__ import annotations

from open_guji_cv.console.routers.step8 import DecideIn, _events_for


def _mk(**kw):
    d = DecideIn(book="bxgb", pair=["甲", "乙"], ids=["bxgb:3:1:1"], **kw)
    return _events_for(d, 0, "bxgb-collate")


def _kinds(evs):
    return sorted({e.kind for e in evs})


def test_ours_books_each_cell():
    """我方对：逐格记账，下轮不再出卡。"""
    d = DecideIn(book="bxgb", pair=["甲", "乙"],
                 ids=["bxgb:3:1:1", "bxgb:9:2:3"], who="ours")
    evs = _events_for(d, 0, "b")
    assert _kinds(evs) == ["collate_ok"] and len(evs) == 2


def test_theirs_rewrites_each_cell_via_confirm():
    """校对本对 = 我们认错了 → 复用 Step7 的 confirm 通道（改字＋入库）。"""
    d = DecideIn(book="bxgb", pair=["甲", "乙"],
                 ids=["bxgb:3:1:1", "bxgb:9:2:3"], who="theirs")
    evs = _events_for(d, 0, "b")
    assert _kinds(evs) == ["confirm"] and len(evs) == 2
    assert all(e.payload["shape"] == "乙" for e in evs), "要改成校对本那个字"


def test_neither_uses_the_typed_char():
    """都不对：两边都错，录人输入的字。"""
    evs = _mk(who="neither", fix="丙")
    assert _kinds(evs) == ["confirm"]
    assert evs[0].payload["shape"] == "丙"


def test_jiajie_is_recorded_once_per_pair():
    """通假是贴给**字对**的跨书标签，不随字位数增加。"""
    d = DecideIn(book="bxgb", pair=["甫", "父"],
                 ids=["a:1:1:1", "a:2:2:2", "a:3:3:3"], who="ours", rel="jiajie")
    evs = _events_for(d, 0, "b")
    assert [e.kind for e in evs].count("mark_jiajie") == 1
    assert [e.kind for e in evs].count("collate_ok") == 3


def test_book_convention_and_deny_are_pair_level():
    assert _kinds(_mk(kind="人名")) == ["char_convention"]
    assert _kinds(_mk(kind="不是异体")) == ["variant_deny"]


def test_book_kind_jiajie_moves_the_pair():
    """② 里选「通假」也要搬家——不能只写进书配置。"""
    assert _kinds(_mk(kind="通假")) == ["mark_jiajie"]


def test_empty_verdict_makes_no_events():
    """who/kind 都空 = 没裁，不该凭空写事件。"""
    assert _events_for(DecideIn(book="b", pair=["甲", "乙"], ids=["x:1:1:1"]), 0, "b") == []


def test_seq_is_continuous():
    d = DecideIn(book="bxgb", pair=["甫", "父"],
                 ids=["a:1:1:1", "a:2:2:2"], who="ours", rel="jiajie")
    evs = _events_for(d, 100, "b")
    assert [e.seq for e in evs] == [101, 102, 103]
