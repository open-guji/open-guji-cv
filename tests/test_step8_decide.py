# -*- coding: utf-8 -*-
"""Step8 复核裁决 → 事件（2026-09-24 两层分类）。

只测 `_events_for`（挪进哪一类 → 写哪些事件），不起服务：这段是「点哪个按钮落到哪」
的唯一真相源，落库那头另有 test_collate_consumers 覆盖。

钉住的规则：
- 每个字位一条 `collate_verdict`，条数跟着 `ids` 走（「N 处一起裁」不勾只一个）；
- **最终的字变了才写 `confirm`**——挪回「我方对」/ 退回待审也要写，否则先点
  「校对本对」再挪回来，那一格会一直是校对本的字；
- 通假是贴给字对的跨书标签：本书有无一处归通假变了，才 mark / unmark 一次。
"""
from __future__ import annotations

from open_guji_cv.console.routers.step8 import DecideIn, _check, _events_for

P = ["甲", "乙"]


def _row(i, who="pending", cat=None, fix="", basis="", final="甲"):
    return {"id": f"bxgb:3:1:{i}", "pair": tuple(P), "who": who, "cat": cat, "fix": fix,
            "basis": basis, "final": final, "page": 3, "col": 1, "slot": i, "sub": None,
            "hyp_ctx": "…甲…", "ref_ctx": "…乙…"}


def _cur(*rows):
    return {r["id"]: r for r in rows}


def _mk(ids, current, jiajie=frozenset(), pair=P, **kw):
    d = DecideIn(book="bxgb", pair=pair, ids=ids, **kw)
    return _events_for(d, 0, "bxgb-collate", current, set(jiajie))


def _kinds(evs):
    return [e.kind for e in evs]


def test_ours_on_pending_only_records_state():
    """待审 → 我方对：字没变，不写 confirm、不入库。"""
    cur = _cur(_row(1), _row(2))
    evs = _mk(["bxgb:3:1:1", "bxgb:3:1:2"], cur, who="ours", cat="other")
    assert _kinds(evs) == ["collate_verdict"] * 2
    p = evs[0].payload
    assert (p["who"], p["cat"], p["final"]) == ("ours", "other", "甲")
    assert p["ctx"]["hyp_ctx"] == "…甲…", "要带上下文快照：差异消失后还得列得出来"


def test_theirs_rewrites_each_cell():
    evs = _mk(["bxgb:3:1:1", "bxgb:3:1:2"], _cur(_row(1), _row(2)), who="theirs")
    assert _kinds(evs) == ["collate_verdict", "confirm", "collate_verdict", "confirm"]
    c = [e for e in evs if e.kind == "confirm"]
    assert all(e.payload["shape"] == "乙" and e.payload["via"] == "collate_verdict" for e in c)


def test_neither_uses_the_typed_char():
    evs = _mk(["bxgb:3:1:1"], _cur(_row(1)), who="neither", fix=" 丙 ")
    assert [e.payload.get("shape") for e in evs if e.kind == "confirm"] == ["丙"]
    assert evs[0].payload["fix"] == "丙"


def test_moving_back_to_ours_reverts_the_char():
    """校对本对 → 挪回我方对：那一格要改回我方的字。"""
    cur = _cur(_row(1, who="theirs", basis="human", final="乙"))
    evs = _mk(["bxgb:3:1:1"], cur, who="ours", cat="variant")
    assert [e.payload["shape"] for e in evs if e.kind == "confirm"] == ["甲"]


def test_retract_to_pending_reverts_too():
    cur = _cur(_row(1, who="neither", fix="丙", basis="human", final="丙"))
    evs = _mk(["bxgb:3:1:1"], cur, who="")
    assert evs[0].payload["who"] == ""
    assert [e.payload["shape"] for e in evs if e.kind == "confirm"] == ["甲"]


def test_same_final_no_confirm():
    """都不对 丙 → 都不对 丙（改小类之类）不重复入库。"""
    cur = _cur(_row(1, who="neither", fix="丙", basis="human", final="丙"))
    assert _kinds(_mk(["bxgb:3:1:1"], cur, who="neither", fix="丙")) == ["collate_verdict"]


def test_jiajie_marked_once_per_pair():
    cur = _cur(_row(1), _row(2), _row(3))
    evs = _mk(list(cur), cur, who="ours", cat="jiajie")
    assert _kinds(evs).count("mark_jiajie") == 1
    assert _kinds(evs).count("collate_verdict") == 3


def test_jiajie_not_remarked_if_known():
    cur = _cur(_row(1))
    assert "mark_jiajie" not in _kinds(_mk(["bxgb:3:1:1"], cur, jiajie={tuple(P)},
                                           who="ours", cat="jiajie"))


def test_unmark_when_last_jiajie_moves_out():
    cur = _cur(_row(1, who="ours", cat="jiajie", basis="human"),
               _row(2, who="ours", cat="jiajie", basis="human"))
    # 只挪走一处：另一处仍是通假，不撤
    assert "unmark_jiajie" not in _kinds(_mk(["bxgb:3:1:1"], cur, jiajie={tuple(P)},
                                             who="ours", cat="other"))
    evs = _mk(list(cur), cur, jiajie={tuple(P)}, who="ours", cat="other")
    un = [e for e in evs if e.kind == "unmark_jiajie"]
    assert len(un) == 1 and un[0].payload["book"] == "bxgb"


def test_auto_jiajie_left_behind_keeps_the_mark():
    """旧 ② 层点「通假」只记字对：剩下的几处是按表自动归的，挪走一处不能把表撤了。"""
    cur = _cur(_row(1, who="ours", cat="jiajie", basis="auto"),
               _row(2, who="ours", cat="jiajie", basis="auto"))
    assert "unmark_jiajie" not in _kinds(_mk(["bxgb:3:1:1"], cur, jiajie={tuple(P)},
                                             who="theirs"))


def test_seq_is_continuous():
    cur = _cur(_row(1), _row(2))
    evs = _mk(list(cur), cur, who="theirs")
    d = DecideIn(book="bxgb", pair=P, ids=list(cur), who="theirs")
    assert [e.seq for e in _events_for(d, 100, "b", cur, set())] == [101, 102, 103, 104]
    assert len(evs) == 4


def test_check_rejects_bad_input():
    ok = dict(book="b", pair=P, ids=["x:1:1:1"])
    assert _check(DecideIn(**ok, who="ours", cat="variant")) == ""
    assert _check(DecideIn(**ok, who="")) == "", "空 = 退回待审，是合法的"
    assert _check(DecideIn(**ok, who="deny"))
    assert _check(DecideIn(**ok, who="ours", cat="人名"))
    assert _check(DecideIn(**ok, who="neither", fix=""))
    assert _check(DecideIn(**ok, who="neither", fix="丙丁"))
    assert _check(DecideIn(book="b", pair=["甲", "甲"], ids=["x:1:1:1"], who="ours"))
    assert _check(DecideIn(book="b", pair=P, ids=[], who="ours"))
