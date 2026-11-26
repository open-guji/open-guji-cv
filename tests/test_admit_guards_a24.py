# -*- coding: utf-8 -*-
"""A24 2026-10-23 放行护栏（殿本 vol11/14/15 用 v0.5.9 重跑后逐格核出的错放）：context 不在异体里选形、铁证与上下文互证、
库×整理本近平手、字组补放与整理本互证。自造数据。"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.groups.flow import FlowConfig, group_flow_pass
from open_guji_cv.steps.seed_admit import (SeedAdmitParams, _context_lib_dissent, _context_variant_tie,
                                           _iron_ctx_dissent, _lib_near_tie)


class _VM:
    """语义表：參㕘叅、簒篡、黃黄 各算一字，其余各自为字。"""
    _SEM = {"㕘": "參", "叅": "參", "簒": "篡", "黄": "黃"}

    def semantic(self, c):
        return self._SEM.get(c, c)


VM = _VM()


def _dec(ch, ranked):
    return SimpleNamespace(char=ch, ranked=ranked)


def test_context_variant_tie():
    # vol14 235:7:4：㕘/叅 各约 0.5，库 㕘 0.9725／叅 0.955（差 0.0175 < 0.02）→ 抓阄，拦
    assert _context_variant_tie(_dec("叅", [("叅", 0.5002), ("㕘", 0.4998)]),
                                [("叅", 0.9739), ("㕘", 0.9725)], VM, 0.25, 0.02)
    # 库形分得开（放行字领先 0.05）→ 不拦
    assert not _context_variant_tie(_dec("叅", [("叅", 0.5), ("㕘", 0.5)]),
                                    [("叅", 0.99), ("㕘", 0.94)], VM, 0.25, 0.02)
    # 对手不在库候选里（库里没有简体 黄）→ 刻形分得开，不拦
    assert not _context_variant_tie(_dec("黃", [("黃", 0.6), ("黄", 0.4)]), [("黃", 0.98)], VM, 0.25, 0.02)
    # 对手概率太低 → 不拦；语义不同的对手不归这条管
    assert not _context_variant_tie(_dec("叅", [("叅", 0.9), ("㕘", 0.1)]),
                                    [("叅", 0.97), ("㕘", 0.97)], VM, 0.25, 0.02)
    assert not _context_variant_tie(_dec("相", [("相", 0.5), ("杞", 0.5)]),
                                    [("相", 0.97), ("杞", 0.97)], VM, 0.25, 0.02)
    # 书级码位归一后同字的不算
    assert not _context_variant_tie(_dec("叅", [("叅", 0.5), ("㕘", 0.5)]),
                                    [("叅", 0.97), ("㕘", 0.97)], VM, 0.25, 0.02, canon=lambda c: "參")


def test_iron_ctx_dissent():
    # vol11 12:2:14：库 宫 0.9972／官 0.9961，上下文 官 0.69 → 拦
    assert _iron_ctx_dissent("宫", _dec("官", [("官", 0.69), ("宫", 0.31)]),
                             [("宫", 0.9972), ("官", 0.9961)], VM, 0.5, 0.005)
    assert not _iron_ctx_dissent("宫", _dec("官", [("官", 0.4), ("宫", 0.31)]),
                                 [("宫", 0.9972), ("官", 0.9961)], VM, 0.5, 0.005)       # 上下文没把握
    assert not _iron_ctx_dissent("宫", _dec("官", [("官", 0.9)]),
                                 [("宫", 0.9972), ("官", 0.97)], VM, 0.5, 0.005)         # 库分得开
    assert not _iron_ctx_dissent("宫", _dec("宫", [("宫", 0.9)]), [("宫", 0.99)], VM, 0.5, 0.005)
    assert not _iron_ctx_dissent("宫", None, [("宫", 0.99)], VM, 0.5, 0.005)


def test_context_lib_dissent():
    assert _context_lib_dissent("相", [("𣏌", 0.9836), ("相", 0.9483)], VM, 0.03, 0.93)      # vol14 98:7:17
    assert _context_lib_dissent("書", [("杳", 0.9754), ("書", 0.933)], VM, 0.03, 0.93)       # vol14 215:9:17
    assert _context_lib_dissent("事", [("奉", 0.9366), ("牽", 0.9335)], VM, 0.03, 0.93)      # 117:9:21，事 不在库候选
    assert not _context_lib_dissent("事", [("奉", 0.90)], VM, 0.03, 0.93)                     # 库也没把握
    assert not _context_lib_dissent("相", [("𣏌", 0.96), ("相", 0.95)], VM, 0.03, 0.93)       # 差得不多
    assert not _context_lib_dissent("㕘", [("叅", 0.99), ("㕘", 0.90)], VM, 0.03, 0.93)       # 语义同字归异体那条管
    assert not _context_lib_dissent("相", [], VM, 0.03, 0.93)


def test_lib_near_tie():
    assert _lib_near_tie([("撰", 0.9393), ("撤", 0.9391)], VM, 0.003)        # vol14 60:1:5
    assert not _lib_near_tie([("撰", 0.95), ("撤", 0.93)], VM, 0.003)
    assert not _lib_near_tie([("叅", 0.95), ("㕘", 0.949)], VM, 0.003)       # 语义同字不算
    assert not _lib_near_tie([("撰", 0.95)], VM, 0.003)


def test_params_dump_hides_guards_when_off():
    d = SeedAdmitParams(context_variant_form_guard=False, iron_ctx_guard=False, match_tie_guard=False).model_dump()
    assert not any(k in d for k in ("context_variant_form_guard", "context_variant_ratio", "iron_ctx_guard",
                                    "iron_ctx_prob", "match_tie_guard", "match_tie_gap"))
    assert "match_tie_guard" not in SeedAdmitParams().model_dump()          # 缺省关
    assert SeedAdmitParams(match_tie_guard=True).model_dump()["match_tie_gap"] == 0.003


@dataclass
class Rec:
    id: str
    char: str | None = None
    admit: bool = False
    channel: str | None = None
    provenance: str = ""
    doubts: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


def test_lift_ref_dissent(monkeypatch):
    """vol15 118:4:15：只有文意给 而，整理本是 面（组内另一字），字形路弃权 → 不补放；字形路也给 而才补放；开关可关。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    picks = {"ctx": "而"}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(picks.get(name), via=name))
    cands = lambda cid: [("而", 0.994), ("面", 0.9785)]
    amap = {"x": ("面", "equal")}
    r = Rec("x")
    group_flow_pass([r], amap, cands, lambda r: False, FlowConfig(groups=("em",)))
    assert not r.admit and "group_flow_ref_dissent" in r.doubts
    r = Rec("x")
    group_flow_pass([r], amap, cands, lambda r: False, FlowConfig(groups=("em",), lift_ref_guard=False))
    assert r.admit and r.char == "而"
    r = Rec("x")
    group_flow_pass([r], {}, cands, lambda r: False, FlowConfig(groups=("em",)))
    assert r.admit and r.char == "而"                     # 没有整理本字：照旧补放
    picks.update({k: "而" for k in flow.GROUPS["em"].flow.solvers})
    r = Rec("x")
    group_flow_pass([r], amap, cands, lambda r: False, FlowConfig(groups=("em",)))
    assert r.admit and r.char == "而"                     # 非文意解法也给 而：补放


def test_lift_coord_dissent(monkeypatch):
    """vol18 107:6:7：现役对位缺格，坐标对位是组外的 叔，组给 叙 → 不补放；坐标对位是组内字或没有时照旧。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    g = "em"
    mem = sorted(flow.GROUPS[g].members)
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(mem[0], via=name))
    cands = lambda cid: [(mem[0], 0.994), (mem[1], 0.9785)]
    r = Rec("x")
    group_flow_pass([r], {}, cands, lambda r: False, FlowConfig(groups=(g,)), veto_refs={"x": "叔"})
    assert not r.admit and "group_flow_coord_dissent" in r.doubts
    r = Rec("x")
    group_flow_pass([r], {}, cands, lambda r: False, FlowConfig(groups=(g,)), veto_refs={"x": mem[1]})
    assert r.admit and r.char == mem[0]                  # 组内另一字：坐标对位不拦
    r = Rec("x")
    group_flow_pass([r], {}, cands, lambda r: False, FlowConfig(groups=(g,), lift_ref_guard=False),
                    veto_refs={"x": "叔"})
    assert r.admit and r.char == mem[0]


# —— 接进 seed_admit ——

def _run_ctx(tmp_path, monkeypatch, cands, dec, params=None):
    from helpers import make_book, make_ctx, page_decision, page_match, write_product
    from open_guji_cv.core.step import STEPS
    ctx = make_ctx(tmp_path, make_book("tbook"), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(1, "tbook", col=1, recs=[
        dict(slot=1, verdict="unsure", cov=cands[0][1], wmax=10.0, candidates=list(cands))]))
    write_product(ctx, "context_decide", 1, context_decision=page_decision(
        1, "tbook", col=1, recs=[dict(slot=1, source="context", **dec)]))
    ctx.params["seed_admit"] = SeedAdmitParams(**{"patch_missing": "skip", "context_page_end_review": False, **(params or {})})
    return STEPS["seed_admit"].run_page(ctx, 1)["seed_admit"].columns[0].chars[0]


def test_seed_admit_context_variant_form(tmp_path, monkeypatch):
    from open_guji_cv.clustering.variants import VariantMap
    if VariantMap.load().semantic("叅") != VariantMap.load().semantic("㕘"):
        import pytest
        pytest.skip("语义表里 叅/㕘 不同义")
    cands = [("叅", 0.9739), ("㕘", 0.9725)]
    dec = dict(char="叅", margin=1.0, ranked=[("叅", 0.5002), ("㕘", 0.4998)])
    r = _run_ctx(tmp_path, monkeypatch, cands, dec)
    assert not r.admit and "context_variant_form" in r.doubts
    r = _run_ctx(tmp_path, monkeypatch, cands, dec, {"context_variant_form_guard": False})
    assert r.admit and r.channel == "context" and r.char == "叅"


def test_seed_admit_context_page_end(tmp_path, monkeypatch):
    # 页末格整理本对位常丢（只收两头 equal 夹住的 replace），context 字改送审
    cands = [("事", 0.95), ("牽", 0.90)]
    dec = dict(char="事", margin=0.9, ranked=[("事", 0.9), ("牽", 0.05)])
    r = _run_ctx(tmp_path, monkeypatch, cands, dec, {"context_page_end_review": True})
    assert not r.admit and "context_page_end" in r.doubts
    r = _run_ctx(tmp_path, monkeypatch, cands, dec)
    assert r.admit and r.channel == "context"


import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")   # 老测试按「放行开关缺省全关」造的数据，见 conftest


def test_lift_ref_agree(monkeypatch):
    """口框族 kou（2026-10-24）：字形给的字须与整理本（缺时坐标对位字）同字才补放；不同 → ref_dissent，两者都没有 → ref_missing。"""
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.protocol import GroupVerdict
    from open_guji_cv.steps.seed_admit import _LANE_REF_REVIEW
    assert flow.GROUPS["kou"].flow.lift_ref_agree
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict("國", via=name))
    cands = lambda cid: [("圓", 0.981), ("國", 0.977), ("圖", 0.971)]
    cfg = FlowConfig(groups=("yt", "kou"))
    r = Rec("x")
    group_flow_pass([r], {"x": ("國", "replace")}, cands, lambda r: False, cfg)
    assert r.admit and r.char == "國" and r.evidence["group"]["id"] == "kou"
    r = Rec("x")
    group_flow_pass([r], {"x": ("圓", "equal")}, cands, lambda r: False, cfg)
    assert not r.admit and "group_flow_ref_dissent" in r.doubts and "group_flow_ref_dissent" in _LANE_REF_REVIEW
    r = Rec("x")
    group_flow_pass([r], {}, cands, lambda r: False, cfg, veto_refs={"x": "國"})
    assert r.admit and r.char == "國"                     # 整理本缺格：坐标对位字同字也行
    r = Rec("x")
    group_flow_pass([r], {}, cands, lambda r: False, cfg)
    assert not r.admit and "group_flow_ref_missing" in r.doubts


def test_kou_yields_to_yt():
    """只有 圓 圖 两个候选的格归 yt（文意，册里排在前）；带 國 等的格才归 kou。"""
    from open_guji_cv.groups.flow import entry
    cfg = FlowConfig(groups=("yt", "kou"))
    assert entry(Rec("x"), [("圖", 0.97), ("圓", 0.96)], "圓", cfg) == ("yt", "lift")
    assert entry(Rec("x"), [("圖", 0.97), ("國", 0.96)], "國", cfg) == ("kou", "lift")
    assert entry(Rec("x"), [("圖", 0.97), ("團", 0.96)], "圖", cfg) is None        # 團 不在组里（殿本无模板）
