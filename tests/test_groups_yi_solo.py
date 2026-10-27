# -*- coding: utf-8 -*-
"""彝 yi_560（A24 2026-10-26）：整理本缺字（坐标对位 〓）只凭字形补放、三段 margin 门槛；复核按 margin 改字。自造数据。"""
from __future__ import annotations

from dataclasses import dataclass, field

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.groups import flow
from open_guji_cv.groups.flow import FlowConfig, _margin, group_flow_pass
from open_guji_cv.groups.protocol import GroupVerdict

G = "yi_560"


@dataclass
class Rec:
    id: str
    char: str | None = None
    admit: bool = False
    channel: str | None = None
    provenance: str = ""
    doubts: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


def _ids(char, margins):
    def solve(name, g, r, *a, **k):
        if name == "ids":
            return GroupVerdict(char, conf=min(margins), why="agree", via="ids", extra={"margins": list(margins)})
        return GroupVerdict(None, why="abstain:mixed", via=name)
    return solve


CANDS = lambda cid: [("𢑱", 0.979), ("𢑴", 0.978), ("彚", 0.955)]


def _lift(monkeypatch, margins, coord, amap=None, cands=CANDS):
    monkeypatch.setattr(flow, "_solve", _ids("𢑱", margins))
    r = Rec("x")
    group_flow_pass([r], amap or {}, cands, lambda r: False, FlowConfig(groups=(G,)), veto_refs={"x": coord} if coord else {})
    return r


def test_gap_coord_lifts_when_margins_clear(monkeypatch):
    # vol34:47:3:19：坐标对位 〓、U-Net 三段 1.31/0.68/1.04 → 补放 𢑱（不再算组外字的 coord_dissent）
    r = _lift(monkeypatch, (1.31, 0.68, 1.04), "〓")
    assert r.admit and r.char == "𢑱" and r.channel == "group_flow"


def test_gap_coord_low_margin_stays(monkeypatch):
    r = _lift(monkeypatch, (0.95, 0.29, 1.1), "〓")
    assert not r.admit and "group_flow_solo_weak" in r.doubts


def test_no_witness_needs_margin(monkeypatch):
    assert not _lift(monkeypatch, (0.9, 0.1, 0.9), None).admit        # 没有坐标对位也要过门槛
    assert _lift(monkeypatch, (0.9, 0.5, 0.9), None).admit


def test_outside_coord_still_blocks(monkeypatch):
    r = _lift(monkeypatch, (1.0, 1.0, 1.0), "樊")                    # 坐标对位是组外的真字：照旧拦
    assert not r.admit and "group_flow_coord_dissent" in r.doubts


def test_witness_not_gated(monkeypatch):
    # 整理本有组内字：不走 solo 门槛（照旧 IDS 自身门槛）
    r = _lift(monkeypatch, (0.9, 0.1, 0.9), None, amap={"x": ("彛", "equal")})
    assert r.admit and r.char == "𢑱"


def test_tolerate_hui(monkeypatch):
    # 库把 彚 排在分差内：陪衬，不挡进入
    r = _lift(monkeypatch, (1.0, 1.0, 1.0), "〓", cands=lambda cid: [("𢑱", 0.97), ("彚", 0.96)])
    assert r.admit and r.char == "𢑱"


def test_gap_other_group_unchanged(monkeypatch):
    # 没声明 solo_margin 的组：〓 照旧当组外字拦
    g = "em"
    mem = sorted(flow.GROUPS[g].members)
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(mem[0], via=name))
    r = Rec("x")
    group_flow_pass([r], {}, lambda cid: [(mem[0], 0.994), (mem[1], 0.9785)], lambda r: False, FlowConfig(groups=(g,)),
                    veto_refs={"x": "〓"})
    assert not r.admit and "group_flow_coord_dissent" in r.doubts


def _review(monkeypatch, margins):
    monkeypatch.setattr(flow, "_solve", _ids("𢑴", margins))
    r = Rec("x", char="彝", admit=True, channel="match_ref")
    group_flow_pass([r], {"x": ("彝", "equal")}, lambda cid: [("彝", 0.99), ("𢑴", 0.98)], lambda r: False,
                    FlowConfig(groups=(G,)))
    return r


def test_review_fix_by_margin(monkeypatch):
    # vol31:111:1:6：放行 彝、下段明明是 大，U-Net 读 彑米糸大（𢑴）每段 ≥0.78 → 改字
    r = _review(monkeypatch, (0.97, 0.78, 0.88))
    assert r.admit and r.char == "𢑴" and r.evidence["fixed_from"]["char"] == "彝"
    r = _review(monkeypatch, (0.11, 1.12, 0.62))                     # 有一段不到 0.3：只降审
    assert not r.admit and "group_flow_disagree" in r.doubts


def test_margin_helper():
    assert _margin({"margin": 0.7}) == 0.7
    assert _margin({"margins": [0.9, 0.2, 1.0]}) == 0.2
    assert _margin({}) is None
