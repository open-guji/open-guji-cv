# -*- coding: utf-8 -*-
"""Z03 复核推翻（A24 深挖 2026-11-07）：`flow._same_writing`（同写法不降审）与 `flow._agree_fix`（≥2 路图像同给别字改字）。"""
from __future__ import annotations

from open_guji_cv.groups.flow import FlowConfig, _agree_fix, _same_writing
from open_guji_cv.groups.registry import GROUPS


def T(solver, char, margin=None):
    return {"solver": solver, "char": char, "margin": margin}


def test_same_writing_pairs():
    # 殿本／史記 Z03 A 类：宮宫、賓賔、敘叙、敎教 是同一个字的写法
    for a, b in ("宮宫", "賓賔", "敘叙", "敎教"):
        assert _same_writing(a, b) and _same_writing(b, a)
    assert _same_writing("宮", "宮")


def test_same_writing_rejects_different_chars():
    # 不同义形近字（大太、傳傅、玉王、兩雨）绝不算同写法
    for a, b in ("大太", "傳傅", "玉王", "兩雨", "一二"):
        assert not _same_writing(a, b)
    assert not _same_writing(None, "宮")


def test_agree_fix_two_image_routes():
    # 一二：数横画的 yr_bars 与 ids 同给「二」
    assert _agree_fix([T("ctx", None), T("ids", "二", 1.1), T("yr_bars", "二")], "二", GROUPS["yr"].members)


def test_agree_fix_needs_two_distinct_routes():
    assert not _agree_fix([T("ids", "二", 1.1)], "二", GROUPS["yr"].members)
    assert not _agree_fix([T("ctx", "二"), T("ids", "二", 1.1)], "二", GROUPS["yr"].members)   # 文意不算图像路
    assert not _agree_fix([T("ids", "二"), T("ids", "二")], "二", GROUPS["yr"].members)         # 同一路不算两路


def test_agree_fix_char_must_be_member():
    assert not _agree_fix([T("ids", "人"), T("yr_bars", "人")], "人", GROUPS["yr"].members)
    assert not _agree_fix([T("ids", None), T("yr_bars", None)], None, GROUPS["yr"].members)


def test_flowconfig_defaults():
    c = FlowConfig(groups=())
    assert c.same_writing_keep == frozenset() and c.review_fix_agree == frozenset()


def test_seed_admit_defaults_not_in_dump():
    from open_guji_cv.steps.seed_admit import SeedAdmitParams, _SAME_WRITING_KEEP
    p = SeedAdmitParams()
    assert p.group_flow_same_writing_keep == list(_SAME_WRITING_KEEP) and p.group_flow_review_fix_agree == ["yr"]
    d = p.model_dump()
    assert "group_flow_same_writing_keep" not in d and "group_flow_review_fix_agree" not in d
    assert "group_flow_same_writing_keep" in SeedAdmitParams(group_flow_same_writing_keep=[]).model_dump()


def _run(monkeypatch, group, char, solved, **cfgkw):
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    from open_guji_cv.groups.flow import group_flow_pass
    from tests.test_group_flow import Rec
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(solved.get(name), via=name))
    r = Rec("a", char, True, "match_solo", "match")
    group_flow_pass([r], {}, lambda cid: [], lambda r: False, FlowConfig(groups=(group,), **cfgkw))
    return r


def test_flow_same_writing_keep_end_to_end(monkeypatch):
    r = _run(monkeypatch, "jiao", "教", {"ids": "敎"}, same_writing_keep=frozenset({"jiao"}), provisional=False)
    assert r.admit and r.char == "教" and "group_flow_disagree" not in r.doubts
    r = _run(monkeypatch, "jiao", "教", {"ids": "敎"}, provisional=False)          # 名单空：照旧降审
    assert not r.admit and "group_flow_disagree" in r.doubts


def test_flow_review_fix_agree_end_to_end(monkeypatch):
    r = _run(monkeypatch, "yr", "一", {"ids": "二", "yr_bars": "二"}, review_fix_agree=frozenset({"yr"}), provisional=False)
    assert r.admit and r.char == "二"
    r = _run(monkeypatch, "yr", "一", {"ids": "二", "yr_bars": "二"}, provisional=False)   # 不开：降审
    assert not r.admit and r.char == "一"


def test_yr_tolerates_zi_in_entry():
    # N01 第 7 轮复查：一 的字块库里排成 二 1.000／一 1.000／子 0.97，子 不再把一二挡在字组门外
    from types import SimpleNamespace
    from open_guji_cv.groups.flow import entry
    r = SimpleNamespace(id="vol48:53:6:12b", char="二", admit=False, channel=None, provenance=None)
    cfg = FlowConfig(groups=("yr",))
    assert entry(r, [("二", 0.9998), ("一", 0.9997), ("子", 0.9844)], "一", cfg) == ("yr", "lift")
    # 子 不是陪衬之外的别的字：同样紧咬的 十 照旧挡门
    assert entry(r, [("二", 0.9998), ("一", 0.9997), ("十", 0.9990)], "一", cfg) is None


def test_dissent_keep_form_support():
    from open_guji_cv.groups.flow import _dissent_keep
    c = lambda x: x
    # r7 殿本 vol88:91:2:21：ids 低 margin 弃权（刻形一）、yr_bars 数出二、整理本＝放行字一、文意没问
    trail = [{"solver": "ctx", "char": None}, {"solver": "ids", "char": None, "form": "一", "margin": 0.82}, {"solver": "yr_bars", "char": "二"}]
    assert not _dissent_keep("yr", trail, "一", "一", c, 1.0)                       # 旧：没人给放行字 → 降审
    assert _dissent_keep("yr", trail, "一", "一", c, 1.0, form_support=True)
    # 刻形不是放行字、或 margin 够大、或整理本不一致：不放
    assert not _dissent_keep("yr", [{"solver": "ids", "char": None, "form": "二", "margin": 0.7}, {"solver": "yr_bars", "char": "二"}], "一", "一", c, 1.0, form_support=True)
    assert not _dissent_keep("yr", [{"solver": "ids", "char": None, "form": "一", "margin": 1.3}, {"solver": "yr_bars", "char": "二"}], "一", "一", c, 1.0, form_support=True)
    assert not _dissent_keep("yr", trail, "一", "二", c, 1.0, form_support=True)
    # 文意给了别字照旧降审
    assert not _dissent_keep("yr", trail + [{"solver": "ctx", "char": "二"}], "一", "一", c, 1.0, form_support=True)
