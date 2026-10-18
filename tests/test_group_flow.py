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
    assert {"mn", "dian", "can", "chen", "li", "shen", "zhi", "jys", "ry", "rr"} <= flows
    check_groups(tuple(flows))
    with pytest.raises(ValueError):
        check_groups(("ts",))           # 没声明 flow
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


def test_entry_ref_via_codepoints():
    canon = {"旨x": "旨"}.get
    assert entry(Rec("a"), [("㫖", 0.98)], "旨x", _cfg(), canon=lambda c: canon(c, c)) == ("zhi", "lift")


def test_entry_review_only_for_review_groups_and_never_human():
    cfg = _cfg()
    assert entry(Rec("a", "己", True, "context"), [], None, cfg) == ("jys", "review")
    assert entry(Rec("a", "㫖", True, "match_ref"), [], None, cfg) is None              # 异体组不复核
    assert entry(Rec("a", "己", True, "human", "human"), [], None, cfg) is None
    assert entry(Rec("a", "己", False, None, "human"), [("己", 0.99)], None, cfg) is None


# —— 解法 ——

def test_freq_decide():
    m = frozenset("旨㫖")
    assert F.decide({"㫖": 41, "旨": 0}, m).char == "㫖"
    assert F.decide({"㫖": 41, "旨": 1}, m).char is None            # 次形不为 0
    assert F.decide({"㫖": 19, "旨": 0}, m).char is None            # 主形不够 20
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
           {"kind": "confirm", "ts": "2026-10-02", "target": {"key": "v:1:1:4"}, "payload": {"v": "not_a_char"}}]
    (ws / "feedback" / "events" / "e.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in evs), encoding="utf-8")
    t = F.build(ws, {"zhi": frozenset("旨㫖")})
    assert t["groups"]["zhi"] == {"㫖": 2, "旨": 0}     # align 不算；事件覆盖库标注；not_a_char 撤掉
    F.write(t, tmp_path / "freq.json")
    assert F.load(tmp_path / "freq.json") == {"zhi": {"㫖": 2, "旨": 0}}
    assert F.fingerprint(tmp_path / "freq.json") != F.fingerprint(None)


# —— 整遍 ——

def test_pass_lift_review_and_evidence():
    seq = [Rec("a"), Rec("b", "己", True, "context"), Rec("c"), Rec("d", doubts=["occluded"])]
    cands = {"a": [("𫎇", 0.98), ("蒙", 0.975)], "c": [("𫎇", 0.95), ("蒙", 0.949)], "d": [("𫎇", 0.99)]}
    res = group_flow_pass(seq, {}, lambda cid: cands.get(cid, []),
                          lambda r: "occluded" in r.doubts, _cfg())
    a, b, c, d = seq
    assert a.admit and a.channel == "group_flow" and a.char == "𫎇" and a.provenance == "match"
    assert a.evidence["group"]["decision"] == "admit" and a.evidence["group"]["id"] == "mn"
    assert not c.admit and "group_flow_abstain" in c.doubts and c.evidence["group"]["decision"] == "review"
    assert "group" not in d.evidence                         # 硬护栏不进
    assert b.admit and b.evidence["group"]["mode"] == "review"   # 没有文意窗口：弃权 → 不动
    assert (res.lifted, res.demoted, res.entered) == (1, 0, 3)


def test_review_demotes_on_disagree(monkeypatch):
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict("已", via=name))
    r = Rec("b", "己", True, "context", "context")
    res = group_flow_pass([r], {}, lambda cid: [], lambda r: False, _cfg())
    assert not r.admit and r.char == "己" and "group_flow_disagree" in r.doubts
    assert r.evidence["demoted_from"] == {"channel": "context", "by": "group_flow"} and res.demoted == 1


def test_agree_combine_conflict(monkeypatch):
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    picks = {"ctx": "人", "rr_img": "入"}
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
