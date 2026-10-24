# -*- coding: utf-8 -*-
"""形近护栏的部首族（2026-10-24，A24）：門族 men、辶族 chuo。只进字组流程表；补放须与整理本同字（`lift_ref_agree`）。
流程用自造候选与打桩的判法；真模板库只验格式与登记，不读真书。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from open_guji_cv.groups import GROUPS
from open_guji_cv.groups import ids_online as O
from open_guji_cv.groups.flow import FlowConfig, entry, group_flow_pass
from open_guji_cv.groups.registry import FLOW_GROUPS, SHAPE_GROUPS


@dataclass
class Rec:
    id: str
    char: str | None = None
    admit: bool = False
    channel: str | None = None
    provenance: str = ""
    doubts: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


@pytest.mark.parametrize("gid,partner,shared", [("men", "wj", "問間"), ("chuo", "yh", "遺還")])
def test_family_is_flow_only_and_shares_with_ctx_group(gid, partner, shared):
    assert gid in SHAPE_GROUPS and gid in FLOW_GROUPS and gid not in GROUPS
    g = FLOW_GROUPS[gid]
    assert g.flow.lift_ref_agree and not g.flow.review
    assert set(shared) <= g.members and not (g.members & g.flow.tolerate)
    assert partner in g.overlaps and gid in GROUPS[partner].overlaps
    root = Path(__file__).resolve().parent.parent
    d = json.loads((root / g.config_dir / "ids_bank.json").read_text(encoding="utf-8"))
    assert d["size"] == O.SPECS[gid].size and set(d["templates"]) >= set(shared)
    assert set(d["templates"]) <= g.members | g.flow.tolerate                 # 进库的组外字都是陪衬


def test_entry_ctx_group_first_family_takes_the_rest():
    """點名 wj 在前：只有 問間 紧咬归 wj；分差内有別的門族字（閩、聞）归 men；有组外非陪衬字不进。"""
    r = Rec("x")
    cfg = FlowConfig(groups=("wj", "men"))
    assert entry(r, [("問", 0.98), ("間", 0.975)], "問", cfg) == ("wj", "lift")
    assert entry(r, [("間", 0.955), ("閩", 0.952), ("聞", 0.951)], "閔", cfg) == ("men", "lift")
    assert entry(r, [("間", 0.955), ("刪", 0.952)], None, cfg) == ("men", "lift")       # 刪 是陪衬
    assert entry(r, [("間", 0.955), ("閩", 0.952)], "閧", cfg) is None                   # 整理本字不在族里
    assert entry(r, [("間", 0.955), ("麕", 0.952)], None, cfg) is None


def _run(monkeypatch, pick, ref=None, coord=None):
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(pick, via=name))
    r = Rec("x")
    amap = {"x": (ref, "replace")} if ref else {}
    group_flow_pass([r], amap, lambda cid: [("間", 0.955), ("閩", 0.952), ("聞", 0.951)], lambda r: False,
                    FlowConfig(groups=("men",)), veto_refs={"x": coord} if coord is not None else None)
    return r


def test_lift_needs_ref_agreement(monkeypatch):
    r = _run(monkeypatch, "閔", ref="閔")
    assert r.admit and r.char == "閔" and r.channel == "group_flow"
    r = _run(monkeypatch, "閔", coord="閔")                     # 现役对位缺这一格：用坐标对位字
    assert r.admit and r.char == "閔"
    r = _run(monkeypatch, "闕", coord="閔")
    assert not r.admit and "group_flow_ref_dissent" in r.doubts and r.evidence["group"]["pick"] is None
    r = _run(monkeypatch, "閔")
    assert not r.admit and "group_flow_ref_missing" in r.doubts
    r = _run(monkeypatch, "閔", coord="")                       # 坐标对位说是空格位：当缺位
    assert not r.admit and "group_flow_ref_missing" in r.doubts
    r = _run(monkeypatch, None, ref="閔")
    assert not r.admit and "group_flow_abstain" in r.doubts


def test_other_groups_unaffected_by_ref_agree(monkeypatch):
    """不声明 `lift_ref_agree` 的组（qin）照旧：方法给字、整理本缺位也补放。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict("禽", via=name))
    r = Rec("x")
    group_flow_pass([r], {}, lambda cid: [("會", 0.96), ("禽", 0.955)], lambda r: False, FlowConfig(groups=("qin",)))
    assert r.admit and r.char == "禽"
