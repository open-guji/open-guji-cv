# -*- coding: utf-8 -*-
"""Step8 复核状态（2026-09-24 两层分类）：事件 → 每个字位归哪一类、最终落哪个字。

钉住四件事：
1. 旧事件（collate_ok / 无 via 的 confirm / mark_jiajie / char_convention）照样读得出——
   那 173 条是用户亲手裁的，不改写日志；
2. 新事件 `collate_verdict` 后到覆盖，`who` 空 = 退回待审；
3. 自动档（避諱/异体/通假）没人裁时进「我方对」对应小类，其余进待审；
4. 报告里已经没有的字位（「校对本对」改字后重跑，差异消失）照样列出，才挪得回来。
"""
from __future__ import annotations

from open_guji_cv.feedback.collate_state import (VIA, build_items, counts, final_char,
                                                 group_items, human_verdicts, seg_flags,
                                                 seg_payload)
from open_guji_cv.feedback.events import EventTarget, make_event

B = "bxgb-collate"


def _ev(seq, kind, payload, key="bxgb:3:1:1", batch=B):
    return make_event(batch, seq, kind,
                      EventTarget(step="step8_collate", unit="cell", key=key, book="bxgb"),
                      payload, source_format="server")


def _diff(i, a, b, kind="sub.other"):
    return {"id": f"bxgb:3:1:{i}", "page": 3, "col": 1, "slot": i, "sub": None,
            "kind": kind, "char": a, "ref": b, "hyp_ctx": f"…{a}…", "ref_ctx": f"…{b}…"}


def _tier(tiers=None):
    tiers = tiers or {}
    return lambda a, b, n: tiers.get((a, b), "dispute")


def test_final_char():
    assert final_char(("甲", "乙"), "ours") == "甲"
    assert final_char(("甲", "乙"), "theirs") == "乙"
    assert final_char(("甲", "乙"), "neither", "丙") == "丙"
    assert final_char(("甲", "乙"), "pending") == "甲"


def test_legacy_events_are_read():
    evs = [
        _ev(1, "collate_ok", {"pair": ["甫", "父"]}, key="bxgb:3:1:1"),
        _ev(2, "mark_jiajie", {"pair": ["甫", "父"]}, key="bxgb:3:1:1"),
        _ev(3, "confirm", {"v": "confirm", "shape": "乙"}, key="bxgb:3:1:2"),
        _ev(4, "confirm", {"v": "confirm", "shape": "丙"}, key="bxgb:3:1:3"),
        _ev(5, "collate_ok", {"pair": ["完", "元"]}, key="bxgb:3:1:4"),
        _ev(6, "char_convention", {"pair": ["完", "元"], "kind": "人名"}, key="bxgb:3:1:4"),
    ]
    lookup = {"bxgb:3:1:1": _diff(1, "甫", "父"), "bxgb:3:1:2": _diff(2, "甲", "乙"),
              "bxgb:3:1:3": _diff(3, "甲", "乙"), "bxgb:3:1:4": _diff(4, "完", "元")}
    v = human_verdicts(evs, "bxgb", lookup.get)
    assert (v["bxgb:3:1:1"].who, v["bxgb:3:1:1"].cat) == ("ours", "jiajie")
    assert v["bxgb:3:1:2"].who == "theirs" and v["bxgb:3:1:2"].final == "乙"
    assert v["bxgb:3:1:3"].who == "neither" and v["bxgb:3:1:3"].final == "丙"
    assert v["bxgb:3:1:4"].cat == "other"


def test_other_batches_are_ignored():
    """Step7 的 confirm 不是 Step8 的裁决。"""
    v = human_verdicts([_ev(1, "confirm", {"shape": "乙"}, batch="bxgb-all-decide")],
                       "bxgb", lambda k: _diff(1, "甲", "乙"))
    assert v == {}


def test_new_verdict_overrides_and_retracts():
    evs = [
        _ev(1, "collate_verdict", {"pair": ["甲", "乙"], "who": "ours", "cat": "other"}),
        _ev(2, "collate_verdict", {"pair": ["甲", "乙"], "who": "theirs"}),
        # 新事件顺手写的 confirm 带 via，不能再被当成旧裁决读一遍
        _ev(3, "confirm", {"shape": "乙", "via": VIA, "pair": ["甲", "乙"]}),
    ]
    v = human_verdicts(evs, "bxgb")
    assert v["bxgb:3:1:1"].who == "theirs"
    evs.append(_ev(4, "collate_verdict", {"pair": ["甲", "乙"], "who": ""}))
    assert human_verdicts(evs, "bxgb") == {}


def test_auto_tiers_go_to_ours_rest_pending():
    diffs = [_diff(1, "衞", "衛"), _diff(2, "今", "虜"), _diff(3, "開", "聞")]
    items = {it["id"]: it for it in build_items(
        diffs, {}, _tier({("衞", "衛"): "variant", ("今", "虜"): "taboo"}))}
    assert (items["bxgb:3:1:1"]["who"], items["bxgb:3:1:1"]["cat"],
            items["bxgb:3:1:1"]["basis"]) == ("ours", "variant", "auto")
    assert items["bxgb:3:1:2"]["cat"] == "taboo"
    assert items["bxgb:3:1:3"]["who"] == "pending"
    assert items["bxgb:3:1:3"]["default_cat"] == "other"


def test_decided_item_missing_from_report_is_still_listed():
    """校对本对 → 改字 → 重跑对勘，差异没了。不列出来就挪不回去。"""
    evs = [_ev(1, "collate_verdict", {"pair": ["甲", "乙"], "who": "theirs",
                                     "ctx": {"page": 3, "col": 1, "slot": 1,
                                             "hyp_ctx": "x", "ref_ctx": "y"}})]
    items = build_items([], human_verdicts(evs, "bxgb"), _tier())
    assert len(items) == 1
    it = items[0]
    assert (it["who"], it["final"], it["page"], it["hyp_ctx"]) == ("theirs", "乙", 3, "x")


def test_neither_after_rerun_keeps_its_pair():
    """都不对 → 改成 丙 → 重跑后这一格是 丙→乙 的差异，仍归那条裁决。"""
    evs = [_ev(1, "collate_verdict", {"pair": ["甲", "乙"], "who": "neither", "fix": "丙"})]
    items = build_items([_diff(1, "丙", "乙")], human_verdicts(evs, "bxgb"), _tier())
    assert items[0]["who"] == "neither" and tuple(items[0]["pair"]) == ("甲", "乙")


def test_stale_verdict_on_a_different_pair_is_dropped():
    """重切后这一格成了别的字：旧裁决不适用，回待审。"""
    evs = [_ev(1, "collate_verdict", {"pair": ["甲", "乙"], "who": "ours", "cat": "other"})]
    items = build_items([_diff(1, "丁", "戊")], human_verdicts(evs, "bxgb"), _tier())
    assert items[0]["who"] == "pending"


def test_groups_split_by_state_and_counts():
    diffs = [_diff(i, "𠊓", "傍") for i in range(1, 5)] + [_diff(9, "開", "聞")]
    evs = [_ev(1, "collate_verdict", {"pair": ["𠊓", "傍"], "who": "ours", "cat": "jiajie"},
               key="bxgb:3:1:1"),
           _ev(2, "collate_verdict", {"pair": ["𠊓", "傍"], "who": "theirs"},
               key="bxgb:3:1:2")]
    items = build_items(diffs, human_verdicts(evs, "bxgb"), _tier())
    gs = group_items(items)
    by = {(tuple(g["pair"]), g["who"]): g for g in gs}
    assert by[(("𠊓", "傍"), "pending")]["n"] == 2
    assert by[(("𠊓", "傍"), "ours")]["ids"] == ["bxgb:3:1:1"]
    c = counts(items)
    assert c["pending"] == {"pairs": 2, "items": 3, "auto": 0}
    assert c["ours"]["items"] == 1 and c["cats"]["jiajie"]["pairs"] == 1
    assert c["theirs"]["items"] == 1 and c["neither"]["items"] == 0


def test_legacy_verdict_gets_ctx_from_old_report():
    """旧 confirm 没带上下文；最新报告里差异已消失 → 从旧报告补，补不到至少从 id 拿坐标出图。"""
    evs = [_ev(1, "confirm", {"v": "confirm", "shape": "乙"}, key="bxgb:25:3:2"),
           _ev(2, "collate_verdict", {"pair": ["丁", "戊"], "who": "theirs"}, key="bxgb:44:5:1a")]
    old = {"bxgb:25:3:2": {**_diff(2, "甲", "乙"), "id": "bxgb:25:3:2", "page": 25, "col": 3}}
    items = {it["id"]: it for it in build_items([], human_verdicts(evs, "bxgb", old.get), _tier())}
    a = items["bxgb:25:3:2"]
    assert (a["page"], a["col"], a["hyp_ctx"]) == (25, 3, "…甲…")
    b = items["bxgb:44:5:1a"]
    assert (b["page"], b["col"], b["slot"], b["sub"]) == (44, 5, 1, "a")


def test_seg_flags_are_independent_of_the_verdict():
    """切分反馈不碰定字：不带 shape，也不被当成「校对本对 / 都不对」读回。"""
    p = seg_payload(["contaminated", "truncated"])
    assert p["v"] == "seg_defect" and "shape" not in p
    assert p["quality"] == "truncated" and p["defect"] == "truncated,contaminated"
    evs = [_ev(1, "collate_verdict", {"pair": ["甲", "乙"], "who": "ours", "cat": "other"}),
           _ev(2, "confirm", p)]
    v = human_verdicts(evs, "bxgb", lambda k: _diff(1, "甲", "乙"))
    assert v["bxgb:3:1:1"].who == "ours"
    assert seg_flags(evs, "bxgb") == {"bxgb:3:1:1": ["truncated", "contaminated"]}


def test_seg_flags_cross_batch_and_clear():
    """Step7 标过的也显示；全不勾 = clean，把旧的盖掉。"""
    evs = [_ev(1, "confirm", {"v": "seg_defect", "quality": "contaminated"}, batch="bxgb-all-decide"),
           _ev(2, "confirm", {"v": "seg_defect", "quality": "truncated"}, key="bxgb:3:1:2")]
    assert seg_flags(evs, "bxgb") == {"bxgb:3:1:1": ["contaminated"], "bxgb:3:1:2": ["truncated"]}
    evs.append(make_event(B, 9, "confirm",
                          EventTarget(step="s", unit="cell", key="bxgb:3:1:2", book="bxgb"),
                          seg_payload([]), ts="2099-01-01T00:00:00Z"))
    assert seg_flags(evs, "bxgb") == {"bxgb:3:1:1": ["contaminated"]}


def test_legacy_event_on_a_cell_without_that_pair_is_ignored():
    """旧台子把 壘→墨 记到了 bxgb:3:1:1（卷端「北」）上：报告里没有这一对，不认。"""
    evs = [_ev(1, "collate_ok", {"pair": ["壘", "墨"]}),
           _ev(2, "confirm", {"v": "confirm", "shape": "墨"})]
    assert human_verdicts(evs, "bxgb", lambda k: None) == {}
    other = _diff(1, "丁", "戊")
    assert human_verdicts(evs[:1], "bxgb", lambda k: other) == {}, "报告里这一格是别的字对"


def test_ours_after_rerun_with_new_ref_goes_pending():
    """我方对 甲→乙，重跑后校对本对齐变了成 甲→丙：是新差异，要进待审，不能归回 甲→乙。"""
    evs = [_ev(1, "collate_verdict", {"pair": ["甲", "乙"], "who": "ours", "cat": "other"})]
    items = build_items([_diff(1, "甲", "丙")], human_verdicts(evs, "bxgb"), _tier())
    assert [(tuple(it["pair"]), it["who"]) for it in items] == [(("甲", "丙"), "pending")]


def test_theirs_after_rerun_with_new_ref_goes_pending():
    """校对本对 甲→乙（改成乙），重跑后成了 乙→丙：同样是新差异。"""
    evs = [_ev(1, "collate_verdict", {"pair": ["甲", "乙"], "who": "theirs"})]
    items = build_items([_diff(1, "乙", "丙")], human_verdicts(evs, "bxgb"), _tier())
    assert [(tuple(it["pair"]), it["who"]) for it in items] == [(("乙", "丙"), "pending")]
