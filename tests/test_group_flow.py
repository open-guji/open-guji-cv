# -*- coding: utf-8 -*-
"""字组统一流程（`seed_admit.group_flow`，新 variant-tie，2026-10-18）：进入规则、各解法、合并、证据；缺省关。自造数据。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_decision, page_match, write_product
from open_guji_cv.core.step import STEPS
from open_guji_cv.groups import GROUPS
from open_guji_cv.groups import freq as F
from open_guji_cv.groups.flow import FlowConfig, check_groups, decide, entry, group_flow_pass
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1


@dataclass
class Rec:
    id: str
    char: str | None = None
    admit: bool = False
    channel: str | None = None
    provenance: str = ""
    doubts: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


def _cfg(**kw):
    return FlowConfig(groups=("zhi", "dian", "jys", "rr"), **kw)


# —— 注册表 ——

def test_flow_groups_declared_and_valid():
    flows = {g for g, s in GROUPS.items() if s.flow}
    assert {"dian", "can", "chen", "shen", "zhi", "jys", "ry", "rr", "ts", "wm", "wxs"} <= flows
    check_groups(tuple(flows))
    with pytest.raises(ValueError):
        check_groups(("nope2",))        # 没注册
    with pytest.raises(ValueError):
        check_groups(("nope",))


# —— 进入 ——

def test_entry_lift_needs_near_candidates_and_ref_in_group():
    cfg = _cfg()
    r = Rec("a")
    assert entry(r, [("㫖", 0.98), ("旨", 0.975)], None, cfg) == ("zhi", "lift")
    assert entry(r, [("㫖", 0.98), ("旨", 0.975)], "旨", cfg) == ("zhi", "lift")
    assert entry(r, [("㫖", 0.98), ("旨", 0.975), ("指", 0.972)], None, cfg) is None   # 组外字紧咬
    assert entry(r, [("㫖", 0.98), ("指", 0.90)], None, cfg) == ("zhi", "lift")         # 远的第二名不挡
    assert entry(r, [("㫖", 0.98)], "指", cfg) is None                                  # 整理本字在组外
    assert entry(r, [("㫖", 0.80)], None, cfg) is None                                  # cov 太低
    assert entry(r, [("慎", 0.99)], None, cfg) is None                                  # 组没点名


def test_entry_tolerates_declared_outsiders_only():
    cfg = FlowConfig(groups=("yi_560",))
    r = Rec("a")
    assert entry(r, [("彝", 0.9535), ("𢑱", 0.9535), ("舞", 0.9359)], None, cfg) == ("yi_560", "lift")   # 舞 是陪衬
    assert entry(r, [("彝", 0.9535), ("尋", 0.94)], None, cfg) == ("yi_560", "lift")
    assert entry(r, [("彝", 0.9535), ("指", 0.94)], None, cfg) is None                                  # 别的组外字照挡


def test_entry_ref_enter_when_top_is_tolerated_outsider():
    """`ref_enter`：库里没有 𮅕，库首位是陪衬 莫，整理本作 算 → 按整理本字进组补放（suan）。"""
    cfg = FlowConfig(groups=("suan",))
    r = Rec("a")
    assert entry(r, [("莫", 0.95), ("集", 0.93)], "算", cfg) == ("suan", "lift")
    assert entry(r, [("莫", 0.95), ("集", 0.93)], None, cfg) is None              # 没有整理本字不进
    assert entry(r, [("莫", 0.95), ("集", 0.93)], "莫", cfg) is None              # 整理本字在组外
    assert entry(r, [("莫", 0.95), ("指", 0.94)], "算", cfg) is None              # 别的组外字紧咬照挡
    assert entry(r, [("莫", 0.95)], "算", FlowConfig(groups=("guanm",))) is None    # 组没点名
    assert entry(r, [("莫", 0.95), ("集", 0.93)], None, cfg, coord_ref="𮅕") == ("suan", "lift")   # 对位缺格用坐标对位字
    men = FlowConfig(groups=("men", "guanm"))
    assert entry(r, [("闡", 0.97), ("間", 0.96)], "闗", men) == ("guanm", "lift")  # 先于门族
    assert entry(r, [("闡", 0.97), ("間", 0.96)], "闡", men) == ("men", "lift")


def test_entry_ref_enter_vol51_99_shape_pairs():
    """vol51–99 新建的 派𣲖 奇竒 歲嵗：库没有少的一形、首位是陪衬（泒 音 熾），整理本在组里 → 按整理本进组补放。"""
    r = Rec("a")
    assert entry(r, [("泒", 0.95), ("孤", 0.94)], "𣲖", FlowConfig(groups=("pai",))) == ("pai", "lift")
    assert entry(r, [("音", 0.95), ("青", 0.94)], "竒", FlowConfig(groups=("qi",))) == ("qi", "lift")
    assert entry(r, [("熾", 0.95), ("歲", 0.94)], "嵗", FlowConfig(groups=("sui",))) == ("sui", "lift")
    assert entry(r, [("泒", 0.95), ("指", 0.94)], "𣲖", FlowConfig(groups=("pai",))) is None    # 别的组外字紧咬照挡


def test_entry_ref_enter_member_xuan():
    """`ref_enter_member`（選𨕖）：库首位 選 是辶族 chuo 的成员、点名在前；整理本作 𨕖 → 先进 xuan。整理本作 選 照旧归 chuo。"""
    r = Rec("a")
    cfg = FlowConfig(groups=("chuo", "xuan"))
    assert entry(r, [("選", 0.96), ("遺", 0.95), ("遵", 0.95)], None, cfg, coord_ref="𨕖") == ("xuan", "lift")
    assert entry(r, [("遺", 0.96), ("選", 0.95)], None, cfg, coord_ref="𨕖") == ("xuan", "lift")   # 首位是陪衬也进
    assert entry(r, [("選", 0.96), ("遺", 0.95)], "選", cfg) == ("chuo", "lift")
    # 库首位 選 与坐标对位 𨕖 同在组里：组外字紧咬也进（`ref_top_enter`，2026-10-28）；整理本是组外字则照挡
    assert entry(r, [("選", 0.96), ("指", 0.95)], None, cfg, coord_ref="𨕖") == ("xuan", "lift")
    assert entry(r, [("選", 0.96), ("指", 0.95)], None, cfg, coord_ref="指") is None


def test_entry_book_level_tolerate_extra():
    """书级追加陪衬（史記文淵閣本 2026-11-01）：曰 与借来库形 田 紧咬，追加后进日曰组；没追加的书照旧挡。"""
    r = Rec("a")
    cands = [("日", 0.977), ("曰", 0.971), ("田", 0.964)]
    assert entry(r, cands, "曰", FlowConfig(groups=("ry", "rm"))) is None
    cfg = FlowConfig(groups=("ry", "rm"), tolerate_extra={"ry": "田四囬臼"})
    assert entry(r, cands, "曰", cfg) == ("ry", "lift")
    assert entry(r, [("日", 0.977), ("指", 0.97)], "曰", cfg) is None              # 别的组外字照挡
    assert entry(r, [("田", 0.98), ("曰", 0.975)], "曰", cfg) == ("ry", "lift")     # 库首位是陪衬、整理本在组里（ref_enter）
    assert "田" not in GROUPS["ry"].flow.tolerate                                   # 注册表不变


def test_tolerate_extra_not_in_params_dump():
    assert "group_flow_tolerate_extra" not in SeedAdmitParams().model_dump()
    d = SeedAdmitParams(group_flow=("ry",), group_flow_tolerate_extra={"ry": "田"}).model_dump()
    assert d["group_flow_tolerate_extra"] == {"ry": "田"}


def test_entry_jys_tolerates_ba():
    cfg = _cfg()
    assert entry(Rec("a"), [("己", 0.99), ("巴", 0.985)], None, cfg) == ("jys", "lift")
    assert entry(Rec("a"), [("己", 0.99), ("目", 0.985)], None, cfg) is None


def test_zh_xz_include_variant_forms():
    """sheldon 10-22：㑹 并入曾會、𧰼 并入象彖（异体写法，文意定字）。"""
    assert {"曾", "會", "㑹"} <= GROUPS["zh"].members and {"象", "彖", "𧰼"} <= GROUPS["xz"].members
    assert entry(Rec("a"), [("會", 0.98), ("㑹", 0.97)], None, FlowConfig(groups=("zh",))) == ("zh", "lift")


def test_two_stage_form_pick():
    """象彖𧰼：文意先定彖／象族，象𧰼同族再按库形最近选形；选不出弃权。"""
    from open_guji_cv.groups.flow import _pick_form
    cfg = FlowConfig(groups=("xz",))
    r = Rec("a")
    assert _pick_form("xz", "彖", r, [("彖", 0.9)], cfg, None, [])[:2] == ("彖", "agree")        # 单字族不再选形
    assert _pick_form("xz", "象", r, [("象", 0.963), ("𧰼", 0.938)], cfg, None, [])[:2] == ("象", "agree")
    assert _pick_form("xz", "象", r, [("𧰼", 0.97), ("象", 0.96)], cfg, None, [])[0] is None      # 太近，弃权
    assert _pick_form("xz", "象", r, [("𧰼", 0.97), ("象", 0.90)], cfg, None, [])[0] == "𧰼"      # 文意定族，刻形定形
    assert _pick_form("xz", "象", r, [("象", 0.80)], cfg, None, [])[0] is None                    # cov 太低


def test_entry_ref_via_codepoints():
    canon = {"旨x": "旨"}.get
    assert entry(Rec("a"), [("㫖", 0.98)], "旨x", _cfg(), canon=lambda c: canon(c, c)) == ("zhi", "lift")


def test_entry_ref_free_group_ignores_ref():
    """己已巳整理本没参考价值（ref_free）：整理本字在组外也照进入；有整理本字的普通组仍被挡。"""
    cfg = _cfg()
    assert GROUPS["jys"].ref_free and not GROUPS["zhi"].ref_free
    assert entry(Rec("a"), [("已", 0.99)], "其", cfg) == ("jys", "lift")
    assert entry(Rec("a", "已", True, "split_ref"), [], "其", cfg) == ("jys", "review")
    assert entry(Rec("a"), [("㫖", 0.98)], "指", cfg) is None


def test_entry_review_only_for_review_groups_and_never_human():
    cfg = _cfg()
    assert entry(Rec("a", "己", True, "context"), [], None, cfg) == ("jys", "review")
    assert entry(Rec("a", "點", True, "match_ref"), [], None, cfg) is None              # 没有字形判法的异体组不复核
    assert entry(Rec("a", "㫖", True, "match_ref"), [], None, cfg) == ("zhi", "review")  # 按刻形复核（SHAPE_REVIEW）
    assert entry(Rec("a", "己", True, "human", "human"), [], None, cfg) is None
    assert entry(Rec("a", "己", False, None, "human"), [("己", 0.99)], None, cfg) is None


# —— 解法 ——

def test_freq_decide():
    m = frozenset("旨㫖")
    assert F.decide({"㫖": 41, "旨": 0}, m).char == "㫖"
    assert F.decide({"㫖": 41, "旨": 1}, m).char is None            # 次形不为 0
    assert F.decide({"㫖": 9, "旨": 0}, m).char is None             # 主形不够 10（10-20 前是 20）
    assert F.decide({"㫖": 12, "旨": 0}, m).char == "㫖"
    assert F.decide({"㫖": 12, "旨": 0}, m, vols={"㫖": 1}, min_vols=2).why == "abstain:one_vol"   # 只来自一册
    assert F.decide({"㫖": 12, "旨": 0}, m, vols={"㫖": 2}, min_vols=2).char == "㫖"
    assert F.decide({"㫖": 12, "旨": 0}, m, vols=None, min_vols=2).char == "㫖"   # 旧表没有册数：不卡
    assert F.decide(None, m).why == "abstain:no_table"


def test_variant_solvers_in_order_first_wins():
    r = Rec("a")
    cfg = _cfg(freq_table={"zhi": {"㫖": 30, "旨": 0}})
    ch, why, trail = decide("zhi", r, [("旨", 0.99), ("㫖", 0.98)], None, cfg)
    assert (ch, why) == ("㫖", "agree") and [t["solver"] for t in trail] == ["freq"]   # 字频成立就不看后面
    ch, why, trail = decide("zhi", r, [("旨", 0.99), ("㫖", 0.98)], None, _cfg())
    assert ch == "旨" and [t["solver"] for t in trail] == ["freq", "ids", "top1"]    # 退回库形最近
    ch, why, _ = decide("zhi", r, [("旨", 0.96), ("㫖", 0.95)], None, _cfg())
    assert ch is None and why == "abstain"


def test_freq_table_roundtrip_and_build(tmp_path):
    ws = tmp_path / "ws"
    (ws / "output" / "glyph_store" / "instances").mkdir(parents=True)
    (ws / "feedback" / "events").mkdir(parents=True)
    inst = [{"instance_id": "v:1:1:1", "label": "㫖", "label_status": "human"},
            {"instance_id": "v:1:1:2", "label": "旨", "label_status": "align"},
            {"instance_id": "v:1:1:3", "label": "旨", "label_status": "human"},
            {"instance_id": "v2:v:1:1:1", "label": "㫖", "label_status": "human"}]   # 同一格带来源前缀，不重复计
    (ws / "output" / "glyph_store" / "instances" / "v.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in inst), encoding="utf-8")
    evs = [{"kind": "confirm", "ts": "2026-10-01", "target": {"key": "v:1:1:3"}, "payload": {"v": "confirm", "shape": "㫖"}},
           {"kind": "confirm", "ts": "2026-10-01", "target": {"key": "v:1:1:4"}, "payload": {"v": "confirm", "shape": "㫖"}},
           {"kind": "confirm", "ts": "2026-10-02", "target": {"key": "v:1:1:4"}, "payload": {"v": "not_a_char"}},
           {"kind": "confirm", "ts": "2026-10-01", "target": {"key": "v:1:1:5"}, "payload": {"v": "confirm", "shape": "旨"}},
           {"kind": "glyph_audit", "ts": "2026-10-03", "target": {"key": "v2:v:1:1:5"},
            "payload": {"v": "relabel", "char": "㫖", "instance_id": "v2:v:1:1:5"}}]   # 体检改字压过更早的 confirm
    (ws / "feedback" / "events" / "e.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in evs), encoding="utf-8")
    t = F.build(ws, {"zhi": frozenset("旨㫖")})
    assert t["groups"]["zhi"] == {"㫖": 3, "旨": 0}     # align 不算；事件覆盖库标注；not_a_char 撤掉
    F.write(t, tmp_path / "freq.json")
    assert F.load(tmp_path / "freq.json") == {"zhi": {"㫖": 3, "旨": 0}}
    assert F.fingerprint(tmp_path / "freq.json") != F.fingerprint(None)


# —— 整遍 ——

def test_pass_lift_review_and_evidence():
    seq = [Rec("a"), Rec("b", "人", True, "context"), Rec("c"), Rec("d", doubts=["occluded"])]
    cands = {"a": [("點", 0.98), ("㸃", 0.975)], "c": [("點", 0.95), ("㸃", 0.949)], "d": [("點", 0.99)]}
    res = group_flow_pass(seq, {}, lambda cid: cands.get(cid, []),
                          lambda r: "occluded" in r.doubts, _cfg())
    a, b, c, d = seq
    assert a.admit and a.channel == "group_flow" and a.char == "點" and a.provenance == "match"
    assert a.evidence["group"]["decision"] == "admit" and a.evidence["group"]["id"] == "dian"
    assert not c.admit and "group_flow_abstain" in c.doubts and c.evidence["group"]["decision"] == "review"
    assert "group" not in d.evidence                         # 硬护栏不进
    assert b.admit and b.evidence["group"]["mode"] == "review"   # 入人八：没有文意窗口、没有字块，弃权 → 不动
    assert (res.lifted, res.demoted, res.entered) == (1, 0, 3)


def test_review_demotes_on_disagree(monkeypatch):
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict("八", via=name))
    r = Rec("b", "人", True, "context", "context")
    res = group_flow_pass([r], {}, lambda cid: [], lambda r: False, _cfg())
    assert not r.admit and r.char == "人" and "group_flow_disagree" in r.doubts
    assert r.evidence["demoted_from"] == {"channel": "context", "by": "group_flow"} and res.demoted == 1


def test_variant_review_runs_only_shape_method(monkeypatch):
    """按刻形复核的异体组（旨㫖）：复核只跑字形方法，不跑字频（字频永远说主形）；判出另一形 → 降审不改字；判不出 → 不动。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    out, ran = {"a": "㫖", "b": None, "c": "旨"}, []

    def solve(name, g, r, *a, **k):
        ran.append(name)
        return GroupVerdict(out[r.id], via=name)
    monkeypatch.setattr(flow, "_solve", solve)
    seq = [Rec(k, "旨", True, "match_solo", "match") for k in "abc"]
    res = group_flow_pass(seq, {}, lambda cid: [], lambda r: False, _cfg(freq_table={"zhi": {"㫖": 30, "旨": 0}}, provisional=False))
    a, b, c = seq
    assert set(ran) == {"ids"}
    assert not a.admit and a.char == "旨" and "group_flow_disagree" in a.doubts and a.evidence["group"]["decision"] == "demote"
    assert b.admit and b.evidence["group"]["decision"] == "keep"
    assert c.admit and c.evidence["group"]["decision"] == "keep"
    assert res.demoted == 1
    ran.clear()
    r = Rec("a")
    decide("zhi", r, [("旨", 0.99)], None, _cfg(freq_table={"zhi": {"㫖": 30, "旨": 0}}))
    assert ran == ["freq"]                                   # 不是复核：照旧跑 methods，第一个给字的说了算


def test_review_conflict_demotes(monkeypatch):
    """复核时两路解法给了不同的字（必有一路≠放行字）→ 降审。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    picks = {"ctx": "人", "rr_img": None, "ids": "入"}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(picks[name], via=name))
    r = Rec("b", "人", True, "match_ref", "match")
    group_flow_pass([r], {}, lambda cid: [], lambda r: False, _cfg())
    assert not r.admit and "group_flow_disagree" in r.doubts


def test_review_weak_vote_overruled(monkeypatch):
    """入人八随机森林是弱票（`review_weak`）：它单独反对、别的路都支持放行字 → 不降；没人支持放行字、或强路也反对 → 照常降。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    picks = {}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(picks[name], via=name))
    for p, kept in (({"ctx": None, "rr_img": "人", "ids": "入"}, True),
                    ({"ctx": "入", "rr_img": "人", "ids": "入"}, True),
                    ({"ctx": None, "rr_img": "人", "ids": None}, False),
                    ({"ctx": "人", "rr_img": "人", "ids": "入"}, False)):
        picks.clear(); picks.update(p)
        r = Rec("b", "入", True, "match_ref", "match")
        group_flow_pass([r], {}, lambda cid: [], lambda r: False, _cfg())
        assert r.admit is kept, p
        if kept:
            assert r.evidence["group"]["decision"] == "keep"
            assert r.evidence["group"]["solvers"][-1] == {"solver": "review_weak", "char": None, "why": "overruled", "weak": ["rr_img"]}


def test_review_fix_margin(monkeypatch):
    """`review_fix_margin`：字形给了另一形、margin ≥0.70 改字（仍放行），0.45–0.70 照常降审。
    原来只有 徵徴 zheng 用（2026-10-27 改成码位组），这里把 呂吕 lv 的门槛临时设成 0.70、借 徵徴 两字来测。"""
    import dataclasses
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    g = flow.GROUPS["lv"]
    monkeypatch.setitem(flow.GROUPS, "lv", dataclasses.replace(
        g, members=frozenset("徵徴"), flow=dataclasses.replace(g.flow, review_fix_margin=0.70)))
    mg = {"h": 0.9, "l": 0.6}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(
        "徴" if name == "ids" else None, via=name, extra={"margin": mg[r.id]} if name == "ids" else {}))
    h, lo = Rec("h", "徵", True, "match_replace", "match"), Rec("l", "徵", True, "match_replace", "match")
    group_flow_pass([h, Rec("m", "中", True), lo], {}, lambda cid: [], lambda r: False, FlowConfig(groups=("lv",)))
    assert (h.char, h.admit, h.evidence["group"]["decision"]) == ("徴", True, "fix")
    assert h.evidence["fixed_from"] == {"channel": "match_replace", "char": "徵"}
    assert not lo.admit and "group_flow_disagree" in lo.doubts and lo.char == "徵"


def test_review_fix_and_abstain_for_jys(monkeypatch):
    """己已巳（`review_fix`＋`review_abstain`）：文意给了别的字就改字（仍放行）；文意弃权就降审。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    out = {"b": "已", "c": None}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(out[r.id], via=name))
    b, c = Rec("b", "巳", True, "split_ref", "match"), Rec("c", "巳", True, "split_ref", "match")
    mid = Rec("m", "中", True, "split_ref", "match")       # 隔开，免得两格相邻按干支 pair 判
    res = group_flow_pass([b, mid, c], {}, lambda cid: [], lambda r: False, _cfg())
    assert b.admit and b.char == "已" and b.channel == "group_flow" and b.provenance == "context"
    assert b.evidence["fixed_from"] == {"channel": "split_ref", "char": "巳"} and b.evidence["group"]["decision"] == "fix"
    assert not c.admit and "group_flow_abstain" in c.doubts and c.evidence["demoted_from"]["channel"] == "split_ref"
    assert (res.lifted, res.demoted) == (0, 1)


def test_jys_pair_is_ganzhi(monkeypatch):
    """己已巳 `pair`：读序紧挨的两格都进了组 → 前「己」后「巳」，不跑方法；三格连着照常跑方法。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(None, via=name))
    a, b = Rec("a", "巳", True, "split_ref", "match"), Rec("b", "已")
    cands = {"b": [("已", 0.97), ("巳", 0.96)]}
    group_flow_pass([Rec("x", "熙", True), a, b, Rec("y", "大", True)], {}, lambda cid: cands.get(cid, []),
                    lambda r: False, _cfg())
    assert (a.char, a.admit, a.evidence["group"]["decision"]) == ("己", True, "fix")
    assert (b.char, b.admit, b.channel) == ("巳", True, "group_flow")
    assert b.evidence["group"]["solvers"][0]["why"] == "agree:pair"
    run = [Rec(k, "已", True, "split_ref", "match") for k in "pqr"]
    group_flow_pass(run, {}, lambda cid: [], lambda r: False, _cfg())
    assert all(not r.admit and "group_flow_abstain" in r.doubts for r in run)


def test_ry_review_fix_only_when_strong(monkeypatch):
    """日曰 `review_fix_strong`：文意答案 strong 且字形没反对才改掉别的通道放的字；不 strong 照旧降审。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    strong = {"s": True, "w": False}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(
        "曰" if name == "ctx" else None, via=name, extra={"strong": True} if name == "ctx" and strong[r.id] else {}))
    s, w = Rec("s", "日", True, "match_ref", "match"), Rec("w", "日", True, "match_ref", "match")
    cfg = FlowConfig(groups=("ry",))
    group_flow_pass([s, Rec("m", "中", True), w], {}, lambda cid: [], lambda r: False, cfg)
    assert (s.char, s.admit, s.evidence["group"]["decision"]) == ("曰", True, "fix")
    assert s.evidence["fixed_from"] == {"channel": "match_ref", "char": "日"}
    assert not w.admit and "group_flow_disagree" in w.doubts
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(
        "曰" if name == "ctx" else "日", via=name, extra={"strong": True} if name == "ctx" else {}))
    c = Rec("c", "日", True, "match_ref", "match")
    group_flow_pass([c], {}, lambda cid: [], lambda r: False, cfg)
    assert not c.admit and "group_flow_disagree" in c.doubts              # 字形明显反对 → 冲突，仍降审


def test_lift_needs_blocks_image_only_lift(monkeypatch):
    """入人八 `lift_needs=("ctx", "ids")`：只有随机森林分类器给字时不补放（留人审 `group_flow_weak`）；
    文意或整字 HOG 给字（且不冲突）才补放。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    picks = {"ctx": None, "rr_img": "人", "ids": None}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(picks[name], via=name))
    r = Rec("x")
    group_flow_pass([r], {}, lambda cid: [("入", 0.96), ("人", 0.94)], lambda r: False, _cfg())
    assert not r.admit and "group_flow_weak" in r.doubts
    picks["ctx"] = "人"
    r = Rec("y")
    group_flow_pass([r], {}, lambda cid: [("入", 0.96), ("人", 0.94)], lambda r: False, _cfg())
    assert r.admit and r.char == "人"
    picks["ctx"], picks["ids"] = None, "人"          # 文意弃权、整字 HOG 给字 → 补放（2026-10-22 字形第二路）
    r = Rec("z")
    group_flow_pass([r], {}, lambda cid: [("入", 0.96), ("人", 0.94)], lambda r: False, _cfg())
    assert r.admit and r.char == "人"


def test_agree_combine_conflict(monkeypatch):
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    picks = {"ctx": "人", "rr_img": "入", "ids": None}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(picks[name], via=name))
    r = Rec("x")
    group_flow_pass([r], {}, lambda cid: [("人", 0.99), ("入", 0.98)], lambda r: False, _cfg())
    assert not r.admit and "group_flow_conflict" in r.doubts


# —— 接进 seed_admit ——

def _run(tmp_path, monkeypatch, cands, params=None):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, col=COL, recs=[
        dict(slot=1, verdict="unsure", cov=cands[0][1], wmax=10.0, candidates=list(cands))]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[dict(slot=1, char=None, margin=0.1, source="prior")]))
    ctx.params["seed_admit"] = SeedAdmitParams(**{"patch_missing": "skip", **(params or {})})
    return STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns[0].chars[0]


def test_seed_admit_default_off_and_params_hidden(tmp_path, monkeypatch):
    assert not _run(tmp_path, monkeypatch, [("點", 0.98), ("㸃", 0.975)]).admit
    assert not any(k.startswith("group_flow") for k in SeedAdmitParams().model_dump())


def test_seed_admit_group_flow_lifts(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, [("點", 0.98), ("㸃", 0.975)], {"group_flow": ("dian",)})
    assert r.admit and r.channel == "group_flow" and r.char == "點"
    assert r.evidence["group"]["solvers"][-1]["solver"] == "top1"


def test_seed_admit_group_flow_freq(tmp_path, monkeypatch):
    t = tmp_path / "freq.json"
    F.write({"version": 1, "source": {}, "groups": {"zhi": {"㫖": 40, "旨": 0}}}, t)
    r = _run(tmp_path, monkeypatch, [("旨", 0.98), ("㫖", 0.975)],
             {"group_flow": ("zhi",), "group_flow_freq": str(t)})
    assert r.admit and r.char == "㫖" and r.evidence["group"]["solvers"][0]["counts"] == {"㫖": 40, "旨": 0}


def test_seed_admit_near_form_cells_enter_group(tmp_path, monkeypatch):
    """形近护栏（疑问 `near_form`、匹配器 `never_match`）不挡字组：己已巳格进流程，文意弃权就留人审并留证据。"""
    r = _run(tmp_path, monkeypatch, [("已", 0.99), ("巳", 0.985)], {"group_flow": ("jys",)})
    assert "near_form" in r.doubts and not r.admit
    assert r.evidence["group"]["id"] == "jys" and r.evidence["group"]["decision"] == "review"
    assert "group_flow_abstain" in r.doubts


def test_group_flow_paths_default_to_workspace(tmp_path, monkeypatch):
    """没给表路径时找工作区约定位置；相对路径按工作区解释。"""
    (tmp_path / "config" / "groups" / "l2").mkdir(parents=True)
    F.write({"version": 1, "source": {}, "groups": {"zhi": {"㫖": 1}}}, tmp_path / "config" / "groups" / "freq.json")
    (tmp_path / "config" / "groups" / "l2" / "jys.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path))
    p = SeedAdmitParams(db_path="x", group_flow=("zhi", "jys"))
    assert p.group_flow_freq == str(tmp_path / "config" / "groups" / "freq.json")
    assert p.group_flow_tables == {"jys": str(tmp_path / "config" / "groups" / "l2" / "jys.json")}
    q = SeedAdmitParams(db_path="x", group_flow=("zhi",), group_flow_freq="other.json")
    assert q.group_flow_freq == str(tmp_path / "other.json")


def test_entry_overlapping_groups_pick_the_one_that_holds_all_close_candidates():
    """日曰 ry／日目 rm 共用「日」：分差内候选全在 ry 归 ry，全在 rm 归 rm，三者混杂（或整理本字不在组内）留人审。"""
    r = Rec("x")
    cfg = FlowConfig(groups=("ry", "rm"))
    assert entry(r, [("日", 0.98), ("曰", 0.975)], None, cfg) == ("ry", "lift")
    assert entry(r, [("日", 0.98), ("目", 0.975)], None, cfg) == ("rm", "lift")
    assert entry(r, [("日", 0.98), ("曰", 0.975), ("目", 0.972)], None, cfg) is None
    assert entry(r, [("日", 0.98)], "目", cfg) == ("rm", "lift")
    assert entry(r, [("日", 0.98)], "曰", cfg) == ("ry", "lift")
    assert entry(r, [("目", 0.98), ("日", 0.975)], "曰", cfg) is None
    adm = Rec("y", char="日", admit=True, channel="match", provenance="match")
    assert entry(adm, [], "目", cfg) == ("rm", "review")
    assert entry(adm, [], "曰", cfg) == ("ry", "review")
    assert entry(adm, [], None, cfg) == ("ry", "review")


def test_entry_joint_when_close_candidates_span_overlapping_groups():
    """日曰目三字紧咬：单组装不下；`joint` 开着时归第一个装得下「组＋共字组」的组，入口记 "joint"。"""
    r = Rec("x")
    three = [("日", 0.98), ("曰", 0.975), ("目", 0.972)]
    assert entry(r, three, None, FlowConfig(groups=("ry", "rm"))) is None
    cfg = FlowConfig(groups=("ry", "rm"), joint=True)
    assert entry(r, three, None, cfg) == ("ry", "joint")
    assert entry(r, [("曰", 0.98), ("目", 0.975), ("日", 0.97)], "曰", cfg) == ("ry", "joint")
    assert entry(r, three, "白", cfg) is None                                   # 整理本字不在并集里
    assert entry(r, three + [("白", 0.971)], None, cfg) is None                  # 组外字紧咬
    assert entry(r, three, None, FlowConfig(groups=("ry",), joint=True)) is None  # 共字组没点名
    assert entry(r, [("日", 0.98), ("曰", 0.975)], None, cfg) == ("ry", "lift")  # 单组装得下照旧


def test_joint_needs_partner_to_confirm_or_rule_out(monkeypatch):
    """ry 定字后问 rm：曰 须 rm 明说「其他」，日 须 rm 也给日；rm 弃权或给目 → 留人审。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    out = {}

    def solve(name, g, r, *a, **k):
        ch, why, *extra = out[(g, name)]
        return GroupVerdict(ch, why=why, via=name, extra=extra[0] if extra else {})
    monkeypatch.setattr(flow, "_solve", solve)
    cfg = FlowConfig(groups=("ry", "rm"), joint=True)
    three = [("日", 0.98), ("曰", 0.975), ("目", 0.972)]

    def run(ry, rm):
        out.update({("ry", "ctx"): ry, ("ry", "ry_shape"): (None, "abstain:aspect"), ("rm", "ctx"): rm})
        r = Rec("x")
        group_flow_pass([r], {}, lambda cid: three, lambda r: False, cfg)
        return r
    r = run(("曰", "agree"), (None, "abstain:other", {"other_conf": "high"}))
    assert r.admit and r.char == "曰" and r.evidence["group"]["mode"] == "joint"
    assert [t["solver"] for t in r.evidence["group"]["solvers"]] == ["ctx", "ry_shape", "rm:ctx"]
    assert run(("日", "agree"), ("日", "agree")).char == "日"
    for rm in ((None, "abstain:low_conf"), ("目", "agree"), ("日", "agree")):
        r = run(("曰", "agree"), rm)
        assert not r.admit and "group_flow_joint" in r.doubts
    r = run(("日", "agree"), (None, "abstain:other", {"other_conf": "high"}))
    assert not r.admit and "group_flow_joint" in r.doubts
    r = run(("曰", "agree"), (None, "abstain:other", {"other_conf": "low"}))          # 「其他」不是 high 不算
    assert not r.admit and "group_flow_joint" in r.doubts
    r = run((None, "abstain:low_conf"), ("日", "agree"))
    assert not r.admit and "group_flow_abstain" in r.doubts



def test_joint_skips_partner_when_panel_confirmed(monkeypatch):
    """ry 的文意字经 L3 二审小组确认（strong＋panel char:…）且不是 rm 的成员（曰）：rm 弃权／说目也不拦（A24 11-01）；日仍须 rm 同意。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    out = {}

    def solve(name, g, r, *a, **k):
        ch, why, *extra = out[(g, name)]
        return GroupVerdict(ch, why=why, via=name, extra=extra[0] if extra else {})
    monkeypatch.setattr(flow, "_solve", solve)
    cfg = FlowConfig(groups=("ry", "rm"), joint=True)
    three = [("日", 0.98), ("曰", 0.975), ("目", 0.972)]
    pn = {"strong": True, "panel": "char:曰h曰m"}

    def run(ry, rm):
        out.update({("ry", "ctx"): ry, ("ry", "ry_shape"): (None, "abstain:aspect"), ("rm", "ctx"): rm})
        r = Rec("x")
        group_flow_pass([r], {}, lambda cid: three, lambda r: False, cfg)
        return r
    for rm in ((None, "abstain:low_conf"), ("目", "agree"), (None, "abstain:other", {"other_conf": "low"})):
        r = run(("曰", "agree", pn), rm)
        assert r.admit and r.char == "曰", rm
        assert r.evidence["group"]["solvers"][-1] == {"solver": "rm:skip", "char": None, "why": "panel_confirmed"}
    r = run(("曰", "agree", {"strong": True}), (None, "abstain:low_conf"))            # strong 但没经小组：照旧要 rm 表态
    assert not r.admit and "group_flow_joint" in r.doubts
    r = run(("日", "agree", {"strong": True, "panel": "char:日h日h"}), ("目", "agree"))   # 日是 rm 的成员：rm 说目就不放
    assert not r.admit and "group_flow_joint" in r.doubts


def test_ry_panel_confirmed_ctx_overrules_shape(monkeypatch):
    """日曰：文意字经二审小组确认时 ry_shape 只算弱票（`ctx_over_panel`），照文意给字；只 strong（表）不够，仍冲突降审。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    ex = {"strong": True, "panel": "char:曰h曰h"}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(
        "曰" if name == "ctx" else "日", via=name, extra=ex if name == "ctx" else {}))
    cfg = FlowConfig(groups=("ry",))
    c = Rec("c", "日", True, "match_ref", "match")
    group_flow_pass([c], {}, lambda cid: [], lambda r: False, cfg)
    assert c.admit and c.char == "曰" and c.evidence["group"]["decision"] == "fix"
    assert c.evidence["group"]["solvers"][-1]["solver"] == "ctx_over"


def test_registry_panel_flags():
    """rm、mz 与 ry 同口径：strong 的文意可复核改字、补放越过整理本；ry 对字形有二审小组压票。"""
    for g in ("rm", "mz", "ry"):
        f = GROUPS[g].flow
        assert f.review_fix_strong and f.strong_over_ref, g
    assert GROUPS["ry"].flow.ctx_over_panel == ("ry_shape",)


def test_rm_other_hands_off_to_ry(monkeypatch):
    """库分差内只有日目（曰 cov 0）→ 格进 rm；rm 明说「其他」(high) 时交 ry 联判，ry 给曰才放（vol13 99:8:18「子女子曰」）。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    out = {}

    def solve(name, g, r, *a, **k):
        ch, why, *extra = out[(g, name)]
        return GroupVerdict(ch, why=why, via=name, extra=extra[0] if extra else {})
    monkeypatch.setattr(flow, "_solve", solve)
    cfg = FlowConfig(groups=("ry", "rm"), joint=True)
    two = [("日", 0.999), ("目", 0.97)]

    def run(ry, rm):
        out.update({("ry", "ctx"): ry, ("ry", "ry_shape"): (None, "abstain:aspect"), ("rm", "ctx"): rm})
        r = Rec("x")
        group_flow_pass([r], {}, lambda cid: two, lambda r: False, cfg)
        return r
    r = run(("曰", "agree"), (None, "abstain:other", {"other_conf": "high"}))
    assert r.admit and r.char == "曰" and r.evidence["group"]["id"] == "ry"
    assert "handoff" in [t["solver"] for t in r.evidence["group"]["solvers"]]
    for ry, rm in ((("日", "agree"), (None, "abstain:other", {"other_conf": "high"})),     # 日在 rm 里，rm 已说不是
                   (("曰", "agree"), (None, "abstain:other", {"other_conf": "low"})),
                   ((None, "abstain:low_conf"), (None, "abstain:other", {"other_conf": "high"}))):
        r = run(ry, rm)
        assert not r.admit and r.evidence["group"]["id"] == "rm"


def test_ry_strong_ctx_overrides_ref_and_l1_with_strong_table_fixes(monkeypatch):
    """日曰：文意 strong 时补放不受整理本拦（ref_dissent）；L1 规则的字与 strong 表一致才记 strong（可改字）。"""
    from open_guji_cv.groups import flow, methods
    from open_guji_cv.groups.methods import CtxRule, Llm, MethodInput
    from open_guji_cv.groups.protocol import GroupVerdict
    out = {}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(
        *out[name][:1], why="agree", via=name, extra=out[name][1] if len(out[name]) > 1 else {}))
    cfg = FlowConfig(groups=("ry",), lift_ref_guard=True)
    cands = [("日", 0.99), ("曰", 0.98)]
    for strong, admit in ((True, True), (False, False)):
        out.update(ctx=("日", {"strong": True} if strong else {}), ry_shape=(None,))
        r = Rec("x")
        group_flow_pass([r], {"x": ("曰", None)}, lambda cid: cands, lambda r: False, cfg)
        assert r.admit is admit and (admit or "group_flow_ref_dissent" in r.doubts)
    monkeypatch.setattr(CtxRule, "_run", lambda self, inp: GroupVerdict("日", why="agree", via="ctx:ctx_l1"))
    tab = {"s": GroupVerdict("日", why="agree", via="ctx:ctx_l3", extra={"strong": True}),
           "w": GroupVerdict("日", why="agree", via="ctx:ctx_l3"),
           "o": GroupVerdict("曰", why="agree", via="ctx:ctx_l3", extra={"strong": True})}
    monkeypatch.setattr(Llm, "applies", lambda self, inp: True)
    monkeypatch.setattr(Llm, "_run", lambda self, inp: tab[inp.cell_id])
    for cid, want in (("s", True), ("w", None), ("o", None)):
        inp = MethodInput(group="ry", members=frozenset("日曰"), cell_id=cid, cands=[], ref=None, cfg=FlowConfig(groups=("ry",)))
        v = methods.CTX.run(inp)
        assert v.char == "日" and v.extra.get("strong") is want

pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")   # 老测试按「放行开关缺省全关」造的数据，见 conftest


def test_yr_flow_bars_and_ref_veto(monkeypatch):
    """一二（2026-10-25）：整字 HOG 不许单独补放；数横可补放；整理本是组里另一个字时谁给字都不补放。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    from open_guji_cv.groups.registry import GROUPS
    f = GROUPS["yr"].flow
    assert f.solvers == ("ctx", "ids", "yr_bars") and f.lift_needs == ("ctx", "yr_bars") and f.lift_ref_veto and f.review
    picks = {"ctx": None, "ids": "二", "yr_bars": None}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(picks[name], via=name))
    cfg = FlowConfig(groups=("yr",))
    cands = lambda cid: [("一", 0.96), ("二", 0.95)]   # noqa: E731
    r = Rec("x")
    group_flow_pass([r], {}, cands, lambda r: False, cfg)
    assert not r.admit and "group_flow_weak" in r.doubts                       # 只有 HOG
    picks["yr_bars"] = "二"
    r = Rec("y")
    group_flow_pass([r], {}, cands, lambda r: False, cfg)
    assert r.admit and r.char == "二"                                           # 整理本缺位：两路字形一致 → 补放
    r = Rec("z")
    group_flow_pass([r], {"z": ("一", "=")}, cands, lambda r: False, cfg)
    assert not r.admit and "group_flow_ref_dissent" in r.doubts                 # 整理本作一 → 不补


def test_tolerate_ref_agree_shi_yu(monkeypatch):
    """形近护栏 N 类（A24 10-26）：日曰 被 師 的一个旧切分刻例挡、于千子 被 亍 挡。陪衬放进门，但分差内有陪衬字的格
    补放须与整理本同字；分差内没有陪衬字的格照旧。"""
    import open_guji_cv.groups.flow as FL
    assert "師" in GROUPS["ry"].flow.tolerate and GROUPS["ry"].flow.tolerate_ref_agree
    assert "亍" in GROUPS["zy"].flow.tolerate and GROUPS["zy"].flow.tolerate_ref_agree
    cfg = FlowConfig(groups=("ry", "rm", "zy", "yz"))
    assert entry(Rec("a"), [("師", 0.999), ("曰", 0.998), ("日", 0.997)], "曰", cfg) == ("ry", "lift")   # 首位是陪衬，按整理本进
    assert entry(Rec("a"), [("曰", 0.999), ("師", 0.998)], "曰", cfg) == ("ry", "lift")
    assert entry(Rec("a"), [("師", 0.999), ("曰", 0.998)], "師", cfg) is None                         # 整理本作 師：不进
    assert entry(Rec("a"), [("千", 0.997), ("于", 0.996), ("亍", 0.987)], "于", cfg) == ("zy", "lift")
    assert entry(Rec("a"), [("亍", 0.997), ("于", 0.996)], "于", cfg) == ("zy", "lift")

    def fake(ch):
        return lambda g, r, cands, ref, cfg, *a, **k: (ch, "agree", [{"solver": "ctx", "char": ch, "why": "agree"},
                                                                 {"solver": "ry_shape", "char": ch, "why": "agree"}])

    def run(cands, ref, ch):
        monkeypatch.setattr(FL, "decide", fake(ch))
        r = Rec("a")
        group_flow_pass([r], {"a": (ref, "=")}, lambda cid: cands, lambda r: False, cfg)
        return r
    r = run([("師", 0.999), ("曰", 0.998), ("日", 0.997)], "曰", "日")
    assert not r.admit and "group_flow_ref_dissent" in r.doubts                                   # 陪衬带进来、与整理本不同字：留人审
    r = run([("師", 0.999), ("曰", 0.998), ("日", 0.997)], "曰", "曰")
    assert r.admit and r.char == "曰"
    r = run([("曰", 0.999), ("日", 0.998)], "曰", "日")
    assert r.admit and r.char == "日"                                                            # 没有陪衬字的格照旧
def test_rr_ctx_over_image(monkeypatch):
    """入人八 `ctx_over`：文意够硬（L2 strong 或 L1 规则）时字形方法的异议只当弱票，补放、复核都照文意；文意不硬照旧冲突。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    picks, ext = {}, {}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(
        picks[name], via=ext.get(name, (name, {}))[0], extra=ext.get(name, (name, {}))[1]))
    cands = lambda cid: [("八", 0.99), ("入", 0.98)]   # noqa: E731
    for e, lifted in (({"ctx": ("ctx_l3", {"strong": True})}, True),
                      ({"ctx": ("ctx:ctx_l1", {})}, True),
                      ({"ctx": ("ctx_l3", {"runs": 3})}, False)):
        picks.clear(); picks.update({"ctx": "入", "rr_img": "八", "ids": "八"}); ext.clear(); ext.update(e)
        r = Rec("x")
        group_flow_pass([r], {}, cands, lambda r: False, _cfg())
        assert r.admit is lifted and (r.char == "入") is lifted, e
        if lifted:
            assert r.evidence["group"]["solvers"][-1] == {"solver": "ctx_over", "char": None, "why": "overruled",
                                                          "weak": ["rr_img", "ids"]}
        else:
            assert "group_flow_conflict" in r.doubts
    # 复核：放行字 八（整理本错）、文意 strong 说 入、HOG 也说 八 → ctx_over 后照文意改字（review_fix_strong）
    picks.clear(); picks.update({"ctx": "入", "rr_img": None, "ids": "八"}); ext.clear(); ext.update({"ctx": ("ctx_l3", {"strong": True})})
    r = Rec("y", "八", True, "match_ref", "match")
    group_flow_pass([r], {}, cands, lambda r: False, _cfg())
    assert r.admit and r.char == "入" and r.evidence["group"]["decision"] == "fix"
    # 文意不 strong：照常降审，不改字
    ext.update({"ctx": ("ctx_l3", {"runs": 1})})
    r = Rec("w", "八", True, "match_ref", "match")
    group_flow_pass([r], {}, cands, lambda r: False, _cfg())
    assert not r.admit and r.char == "八" and "group_flow_disagree" in r.doubts
    ext.update({"ctx": ("ctx_l3", {"strong": True})})
    # 复核：放行字 入、文意 strong 说 入、HOG 说 八 → 不降
    r = Rec("z", "入", True, "match_ref", "match")
    group_flow_pass([r], {}, cands, lambda r: False, _cfg())
    assert r.admit and r.evidence["group"]["decision"] == "keep"


def test_rr_img_only_lift_respects_ref(monkeypatch):
    """入人八 `lift_img_ref_veto`：文意没给字、只有字形给字，整理本是组里另一个字 → 不补放；整理本同字或缺位照常补放。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    picks = {"ctx": None, "rr_img": None, "ids": "八"}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(picks[name], via=name))
    cands = lambda cid: [("八", 0.99), ("入", 0.98)]   # noqa: E731
    r = Rec("a")
    group_flow_pass([r], {"a": ("入", "=")}, cands, lambda r: False, _cfg())
    assert not r.admit and "group_flow_ref_dissent" in r.doubts
    r = Rec("b")
    group_flow_pass([r], {"b": ("八", "=")}, cands, lambda r: False, _cfg())
    assert r.admit and r.char == "八"
    picks.update(ctx="八")
    r = Rec("c")
    group_flow_pass([r], {"c": ("入", "=")}, cands, lambda r: False, _cfg())
    assert r.admit and r.char == "八"                    # 文意也给了这个字：不归本开关管（沿用 lift_ref_guard）
# —— 同一刻法几个码位（`FlowSpec.ref_canon`／`review_ref_agree`，隸𨽾，A24 2026-10-26）——

_CP = {"𨽾": "隷", "𨽻": "隷", "䝉": "𫎇"}


def _canon(c):
    return _CP.get(c, c)


def test_ref_canon_entry_and_review_by_codepoints():
    cfg = FlowConfig(groups=("li", "mn"))
    r = Rec("a")
    # 整理本 隷／𨽻 不是组员，按书级码位归一后与 𨽾 同字：进组
    assert entry(r, [("𨽾", 0.98)], "𨽻", cfg, _canon) == ("li", "lift")
    assert entry(r, [("𨽾", 0.98)], "𨽻", cfg) is None                    # 不给码位照旧拦
    assert entry(r, [("𫎇", 0.98)], "䝉", cfg, _canon) == ("mn", "lift")
    # 已放行 隷（别的通道）也复核
    assert entry(Rec("b", "隷", True, "match_ref"), [], "隷", cfg, _canon) == ("li", "review")


def test_review_same_shape_keeps_and_ref_dissent_demotes(monkeypatch):
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    pick = {"x": "𨽾", "y": "𨽾", "z": "隸"}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(pick[r.id], via=name))
    x = Rec("x", "隷", True, "match_ref")       # 判出 𨽾、放行 隷：同一刻法两码位，不动
    y = Rec("y", "𨽾", True, "match_ref")       # 判出 𨽾、整理本 隸：降审（整理本说是另一形）
    z = Rec("z", "𨽾", True, "match_ref")       # 判出 隸＝整理本：改字
    amap = {"x": ("隷", "equal"), "y": ("隸", "equal"), "z": ("隸", "equal")}
    group_flow_pass([x, y, z], amap, lambda cid: [], lambda r: False, FlowConfig(groups=("li",), provisional=False), canon=_canon)
    assert x.admit and x.char == "隷" and x.evidence["group"]["decision"] == "keep"
    assert not y.admit and "group_flow_ref_dissent" in y.doubts
    assert z.admit and z.char == "隸" and z.evidence["group"]["decision"] == "fix"


def test_mb_rule_strong_and_ref_rule_fix():
    """木本（A24 2026-10-27）：两条以上 L1 规则同说「本」算 strong → 复核改掉库放的「木」、补放越过整理本；
    一条规则须整理本（缺时坐标对位）同字才改，否则照旧降审。用真规则表（`config/groups/mb/rules.yaml`）。"""
    texts = {"a": ("一卷浙江巡撫採進", "明某撰"),          # l1＋l2＋m 等多条 → strong
             "b": ("王楙所見", "亦無之則諸"),              # 只有 r1
             "c": ("王楙所見", "亦無之則諸"),
             "d": ("此其門目卷帙與此", "皆合則猶宋人")}      # 整理本作木，多条规则 → 补放本
    seq = [Rec("a", "木", True, "match_solo", "match"), Rec("b", "木", True, "match_solo", "match"),
           Rec("c", "木", True, "match_solo", "match"), Rec("d")]
    ctx = lambda s, i, step: texts[s[i].id][0 if step < 0 else 1]
    cands = {"d": [("本", 0.99), ("木", 0.98)]}
    group_flow_pass(seq, {"d": ("木", "=")}, lambda cid: cands.get(cid, []), lambda r: False,
                    FlowConfig(groups=("mb",), lift_ref_guard=True), ctx_fn=ctx, veto_refs={"b": "本"})
    a, b, c, d = seq
    assert (a.char, a.admit, a.evidence["group"]["decision"]) == ("本", True, "fix")
    assert (b.char, b.admit, b.evidence["group"]["decision"]) == ("本", True, "fix")      # 一条规则＋坐标对位本
    assert not c.admit and "group_flow_disagree" in c.doubts                               # 一条规则、没有整理本
    assert (d.char, d.admit) == ("本", True)


# —— 暂归一兜底（sheldon 2026-10-27）——

def _pv_run(monkeypatch, recs, amap, cands, g="can", coord=None, **kw):
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    monkeypatch.setattr(flow, "_solve", lambda name, gg, r, *a, **k: GroupVerdict(kw.get("pick", {}).get(r.id), via=name))
    group_flow_pass(recs, amap, lambda cid: cands[cid], lambda r: False, FlowConfig(groups=(g,)), veto_refs=coord or {})
    return recs


def test_provisional_lift_needs_both_witnesses(monkeypatch):
    """方法弃权：库首位与分差内候选、整理本（缺时坐标对位）都在同字写法里 → 放成最常见字形，标 provisional；
    整理本是组外字、没有整理本字、夹注半格只有坐标对位 → 照旧留人审。"""
    ids = ["v:1:1:1", "v:1:1:2", "v:1:1:3", "v:1:1:4", "v:1:1:5", "v:1:1:6a"]
    recs = [Rec(k) for k in ids]
    c = [("㕘", 0.97)]
    cands = dict(zip(ids, [c, [("㕘", 0.97), ("叅", 0.96)], c, c, [("㕘", 0.97), ("參", 0.96)], c]))
    _pv_run(monkeypatch, recs, {ids[0]: ("㕘", "equal"), ids[2]: ("麥", "equal"), ids[4]: ("㕘", "equal")}, cands,
            coord={ids[1]: "叅", ids[5]: "㕘"})
    a, b, c, d, e, f = recs
    assert a.admit and a.char == "參" and a.channel == "group_flow" and a.evidence["group"]["decision"] == "provisional"
    assert a.evidence["group"]["solvers"][-1] == {"solver": "provisional", "char": "參", "why": "fallback:abstain", "witness": "㕘"}
    assert b.admit and b.char == "參"                                   # 坐标对位字也算一路
    assert not c.admit                                                  # 整理本说是组外的字
    assert not d.admit                                                  # 没有整理本字
    assert e.admit and e.char == "參"
    assert not f.admit                                                  # 夹注半格只有坐标对位
    assert flow_is_provisional(a) and not flow_is_provisional(c)


def flow_is_provisional(r):
    from open_guji_cv.groups.flow import is_provisional
    return is_provisional(r)


def test_provisional_keeps_out_non_synonyms(monkeypatch):
    """讖識䜟：識 是另一个字，不进暂归一；分差内有 識 或整理本作 識 都不兜底。卿 是 鄉 的陪衬（形近不同字）同理。"""
    recs = [Rec(k) for k in ("v:1:1:1", "v:1:1:2", "v:1:1:3")]
    cands = {"v:1:1:1": [("䜟", 0.97), ("識", 0.96)], "v:1:1:2": [("䜟", 0.97)], "v:1:1:3": [("䜟", 0.97)]}
    _pv_run(monkeypatch, recs, {"v:1:1:1": ("䜟", "equal"), "v:1:1:2": ("識", "equal"), "v:1:1:3": ("讖", "equal")}, cands, g="chen")
    a, b, c = recs
    assert not a.admit and not b.admit
    assert c.admit and c.char == "䜟" and c.evidence["group"]["decision"] == "provisional"


def test_provisional_review_instead_of_demote(monkeypatch):
    """复核（絕絶 只降不改）：判出另一形要降审的格，放行字在同字写法里 → 不降，放成最常见字形。"""
    x, y = Rec("x", "絕", True, "match_ref"), Rec("y", "絕", True, "match_ref")
    _pv_run(monkeypatch, [x, y], {"x": ("絕", "equal")}, {"x": [], "y": []}, g="jue", pick={"x": "絶", "y": "絶"})
    assert x.admit and x.char == "絶" and x.evidence["group"]["decision"] == "provisional"
    assert x.evidence["fixed_from"] == {"channel": "match_ref", "char": "絕"}
    assert y.admit and y.char == "絶"


def test_provisional_off_and_near_form_groups(monkeypatch):
    from open_guji_cv.groups.registry import FLOW_GROUPS, PROVISIONAL
    # 意思不同的形近字组绝不暂归一；文意＋异体的混合组（象彖𧰼 xz、冠寇冦宼㓂 kgc，A24 11-01）只能归族内的同义写法，forms 不得跨族
    assert all(FLOW_GROUPS[g].kind == "variant" or any(frozenset(p.forms) <= frozenset(fam) for fam in FLOW_GROUPS[g].flow.families)
               for g, p in PROVISIONAL.items())
    assert all(p.to in p.forms and p.forms & FLOW_GROUPS[g].members for g, p in PROVISIONAL.items())
    r = Rec("a")
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    monkeypatch.setattr(flow, "_solve", lambda *a, **k: GroupVerdict(None))
    group_flow_pass([r], {"a": ("㕘", "equal")}, lambda cid: [("㕘", 0.97)], lambda r: False,
                    FlowConfig(groups=("can",), provisional=False))
    assert not r.admit and "group_flow_abstain" in r.doubts


def test_entry_kgc_tsh_cp_li2_round2():
    """第 2 轮（A24 10-28）：冠寇（库首位 冠、整理本 冦）、塡愼（库首位 愼、整理本 塡）、黎𥠖（库首位 藜、整理本 𥠖）进组补放；整理本不在组里照挡。"""
    r = Rec("a")
    assert entry(r, [("冠", 0.957), ("宼", 0.953)], "冦", FlowConfig(groups=("cp_kou4", "kgc"))) == ("kgc", "lift")
    assert entry(r, [("冠", 0.957), ("指", 0.955)], "冦", FlowConfig(groups=("cp_kou4", "kgc"))) == ("kgc", "lift")   # ref_top_enter：组外字紧咬不拦
    assert entry(r, [("冠", 0.957), ("宼", 0.953)], "冕", FlowConfig(groups=("cp_kou4", "kgc"))) is None             # 整理本在组外
    assert entry(r, [("宼", 0.97), ("寇", 0.96)], "寇", FlowConfig(groups=("cp_kou4", "kgc"))) == ("cp_kou4", "lift")   # 分差内只有寇族字：码位组
    assert entry(r, [("宼", 0.97), ("冠", 0.96)], "寇", FlowConfig(groups=("cp_kou4", "kgc"))) == ("kgc", "lift")     # 冠 紧咬：码位组装不下，归文意组
    assert entry(r, [("愼", 0.95), ("慎", 0.94)], "塡", FlowConfig(groups=("shen", "tsh"))) == ("tsh", "lift")
    assert entry(r, [("愼", 0.95), ("慎", 0.94)], "愼", FlowConfig(groups=("shen", "tsh"))) == ("shen", "lift")
    assert entry(r, [("藜", 0.95), ("黎", 0.947), ("蕪", 0.93)], "𥠖", FlowConfig(groups=("cp_li2",))) == ("cp_li2", "lift")
    assert entry(r, [("藜", 0.95), ("黎", 0.947), ("指", 0.94)], "𥠖", FlowConfig(groups=("cp_li2",))) is None       # 别的组外字紧咬照挡
    assert entry(r, [("藜", 0.95), ("黎", 0.947)], "藜", FlowConfig(groups=("cp_li2",))) is None                    # 整理本作 藜 不进


def test_kgc_tsh_two_stage_form_pick_follows_codepoints():
    """文意定族后，族内各写法按书级码位归一给字：冦宼㓂 → 寇、填 → 塡。"""
    from open_guji_cv.groups.flow import _pick_form
    canon = {"冦": "寇", "宼": "寇", "㓂": "寇", "填": "塡", "慎": "愼"}
    cfg = FlowConfig(groups=("kgc", "tsh"), canon=lambda c: canon.get(c, c))
    r = Rec("a")
    assert _pick_form("kgc", "寇", r, [("冠", 0.96)], cfg, None, [])[:2] == ("寇", "agree")
    assert _pick_form("kgc", "冠", r, [("冠", 0.96)], cfg, None, [])[:2] == ("冠", "agree")
    assert _pick_form("tsh", "塡", r, [("愼", 0.96)], cfg, None, [])[:2] == ("塡", "agree")
    assert _pick_form("tsh", "愼", r, [("愼", 0.96)], cfg, None, [])[:2] == ("愼", "agree")


def test_lift_shape_ref_book_level(monkeypatch):
    """书级 `lift_shape_ref`（史記 2026-11-01）：日曰要文意给字才补放；文意弃权、字形路给的字＝整理本（或坐标对位）字时放行。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    picks = {"ctx": None, "ry_shape": "曰"}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(picks.get(name), via=name))
    cands = lambda cid: [("日", 0.98), ("曰", 0.975)]
    on = FlowConfig(groups=("ry",), lift_shape_ref=frozenset({"ry"}))
    r = Rec("x")
    group_flow_pass([r], {"x": ("曰", "equal")}, cands, lambda r: False, FlowConfig(groups=("ry",)))
    assert not r.admit and "group_flow_weak" in r.doubts                       # 缺省照旧
    r = Rec("x")
    group_flow_pass([r], {"x": ("曰", "equal")}, cands, lambda r: False, on)
    assert r.admit and r.char == "曰"
    r = Rec("x")                                                               # 现役对位缺格，坐标对位字
    group_flow_pass([r], {}, cands, lambda r: False, on, veto_refs={"x": "曰"})
    assert r.admit and r.char == "曰"
    r = Rec("x")                                                               # 整理本是另一个字 → 不放
    group_flow_pass([r], {"x": ("日", "equal")}, cands, lambda r: False, on)
    assert not r.admit
    r = Rec("x")                                                               # 没有整理本 → 不放
    group_flow_pass([r], {}, cands, lambda r: False, on)
    assert not r.admit


def test_lift_shape_ref_not_in_params_dump():
    assert "group_flow_lift_shape_ref" not in SeedAdmitParams().model_dump()
    assert SeedAdmitParams(group_flow=("ry",), group_flow_lift_shape_ref=["ry"]).model_dump()["group_flow_lift_shape_ref"] == ["ry"]


def test_provisional_family_fallback_xz_kgc(monkeypatch):
    """混合组（A24 11-01）：文意定族（象𧰼／寇族）、族内字形判不出或与整理本不一 → 暂归一到 象／寇；文意给 彖、整理本在族外照旧留人审。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict

    def run(g, ctx_char, ref, cand):
        r = Rec("a")
        monkeypatch.setattr(flow, "_solve", lambda name, *a, **k: GroupVerdict(ctx_char if name == "ctx" else None, why="agree" if name == "ctx" else "abstain"))
        group_flow_pass([r], {"a": (ref, "equal")}, lambda cid: [(cand, 0.97)], lambda r: False, FlowConfig(groups=(g,)))
        return r

    r = run("kgc", "寇", "㓂", "宼")
    assert r.admit and r.char == "寇" and r.evidence["group"]["decision"] == "provisional"
    assert not run("kgc", "寇", "冠", "宼").admit        # 整理本作 冠（族外）：留人审
    assert not run("kgc", "冠", "冠", "冠").char == "寇"
    r = run("xz", "象", "象", "𧰼")
    assert r.admit and r.char == "象" and r.evidence["group"]["decision"] == "provisional"
    assert not run("xz", "彖", "象", "𧰼").admit        # 文意给 彖：不兜底成 象


def test_abstain_ref_ok_book_level(monkeypatch):
    """书级 `abstain_ref_ok`（史記 2026-11-01）：复核时文意全弃权、已放行字＝整理本字 → 不降审；有解法给别的字照降。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    picks = {"ctx": None}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(picks.get(name), via=name))
    cands = lambda cid: [("已", 0.99), ("己", 0.95)]
    on = FlowConfig(groups=("jys",), abstain_ref_ok=frozenset({"jys"}))
    adm = lambda: Rec("x", "已", True, "split_ref")
    r = adm()
    group_flow_pass([r], {"x": ("已", "equal")}, cands, lambda r: False, FlowConfig(groups=("jys",)))
    assert not r.admit and "group_flow_abstain" in r.doubts                     # 缺省照旧
    r = adm()
    group_flow_pass([r], {"x": ("已", "equal")}, cands, lambda r: False, on)
    assert r.admit and r.char == "已" and r.evidence["group"]["solvers"][-1]["why"] == "abstain_ref_agree"
    r = adm()                                                                  # 现役对位缺格，坐标对位字
    group_flow_pass([r], {}, cands, lambda r: False, on, veto_refs={"x": "已"})
    assert r.admit
    r = adm()                                                                  # 整理本是另一个字 → 照降
    group_flow_pass([r], {"x": ("己", "equal")}, cands, lambda r: False, on)
    assert not r.admit
    r = adm()                                                                  # 没有整理本 → 照降
    group_flow_pass([r], {}, cands, lambda r: False, on)
    assert not r.admit


def test_abstain_ref_ok_not_in_params_dump():
    assert "group_flow_abstain_ref_ok" not in SeedAdmitParams().model_dump()
    d = SeedAdmitParams(group_flow=("jys",), group_flow_abstain_ref_ok=["jys"]).model_dump()
    assert d["group_flow_abstain_ref_ok"] == ["jys"]


def test_abstain_ref_ok_lift_takes_ref_form(monkeypatch):
    """书级 `abstain_ref_ok` 补放一支：曾會㑹 字形定到 會 族、族内刻形拆不开 → 取整理本形 㑹；整理本是族外字（曾）不放。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(
        "會" if name == "ids" else None, why="agree" if name == "ids" else "abstain:x", via=name))
    cands = lambda cid: [("㑹", 0.99), ("會", 0.975)]
    on = FlowConfig(groups=("zh",), abstain_ref_ok=frozenset({"zh"}))
    r = Rec("x")
    group_flow_pass([r], {"x": ("㑹", "equal")}, cands, lambda r: False, FlowConfig(groups=("zh",)))
    assert not r.admit                                                         # 缺省照旧
    r = Rec("x")
    group_flow_pass([r], {"x": ("㑹", "equal")}, cands, lambda r: False, on)
    assert r.admit and r.char == "㑹"
    r = Rec("x")
    group_flow_pass([r], {"x": ("曾", "equal")}, cands, lambda r: False, on)
    assert not r.admit
