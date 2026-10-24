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
    return FlowConfig(groups=("zhi", "mn", "jys", "rr"), **kw)


# —— 注册表 ——

def test_flow_groups_declared_and_valid():
    flows = {g for g, s in GROUPS.items() if s.flow}
    assert {"mn", "dian", "can", "chen", "li", "shen", "zhi", "jys", "ry", "rr", "ts", "wm", "wxs"} <= flows
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
    assert entry(r, [("點", 0.99)], None, cfg) is None                                  # 组没点名


def test_entry_tolerates_declared_outsiders_only():
    cfg = FlowConfig(groups=("yi_560",))
    r = Rec("a")
    assert entry(r, [("彝", 0.9535), ("𢑱", 0.9535), ("舞", 0.9359)], None, cfg) == ("yi_560", "lift")   # 舞 是陪衬
    assert entry(r, [("彝", 0.9535), ("尋", 0.94)], None, cfg) == ("yi_560", "lift")
    assert entry(r, [("彝", 0.9535), ("指", 0.94)], None, cfg) is None                                  # 别的组外字照挡


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
    assert entry(Rec("a", "𫎇", True, "match_ref"), [], None, cfg) is None              # 没有字形判法的异体组不复核
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
    cands = {"a": [("𫎇", 0.98), ("蒙", 0.975)], "c": [("𫎇", 0.95), ("蒙", 0.949)], "d": [("𫎇", 0.99)]}
    res = group_flow_pass(seq, {}, lambda cid: cands.get(cid, []),
                          lambda r: "occluded" in r.doubts, _cfg())
    a, b, c, d = seq
    assert a.admit and a.channel == "group_flow" and a.char == "𫎇" and a.provenance == "match"
    assert a.evidence["group"]["decision"] == "admit" and a.evidence["group"]["id"] == "mn"
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
    res = group_flow_pass(seq, {}, lambda cid: [], lambda r: False, _cfg(freq_table={"zhi": {"㫖": 30, "旨": 0}}))
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
    picks = {"ctx": "人", "rr_img": "入", "ids": None}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(picks[name], via=name))
    r = Rec("b", "人", True, "match_ref", "match")
    group_flow_pass([r], {}, lambda cid: [], lambda r: False, _cfg())
    assert not r.admit and "group_flow_disagree" in r.doubts


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
    assert not _run(tmp_path, monkeypatch, [("𫎇", 0.98), ("蒙", 0.975)]).admit
    assert not any(k.startswith("group_flow") for k in SeedAdmitParams().model_dump())


def test_seed_admit_group_flow_lifts(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, [("𫎇", 0.98), ("蒙", 0.975)], {"group_flow": ("mn",)})
    assert r.admit and r.channel == "group_flow" and r.char == "𫎇"
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
    assert entry(r, three + [("師", 0.971)], None, cfg) is None                  # 组外字紧咬
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


pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")   # 老测试按「放行开关缺省全关」造的数据，见 conftest
