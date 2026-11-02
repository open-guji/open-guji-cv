"""整理本互证降门槛（FlowSpec.ref_margin，A24 2026-11-01）：整字 HOG 只因 margin 不够弃权、第一名是少见形且与整理本字同字 → 放。"""
from open_guji_cv.groups.flow import _ref_lowmargin
from open_guji_cv.groups.registry import FLOW_GROUPS as GROUPS


def _t(form, m, why="abstain:low_margin"):
    return [{"solver": "ids", "char": None, "form": form, "margin": m, "why": why}]


def test_suan_rare_form_with_ref_is_lifted():
    ch, why, trail = _ref_lowmargin("suan", None, "abstain", _t("𮅕", 0.3), "𮅕", lambda c: c)
    assert (ch, why) == ("𮅕", "agree")
    assert trail[-1]["solver"] == "ref_lowmargin" and trail[-1]["witness"] == "𮅕"


def test_not_lifted_when_margin_too_low_ref_differs_or_common_form():
    f = lambda c: c  # noqa: E731
    assert _ref_lowmargin("suan", None, "abstain", _t("𮅕", 0.05), "𮅕", f)[0] is None      # margin 不够
    assert _ref_lowmargin("suan", None, "abstain", _t("𮅕", 0.5), "莫", f)[0] is None       # 整理本不是这一形
    assert _ref_lowmargin("suan", None, "abstain", _t("算", 0.5), "算", f)[0] is None       # 常见形不放宽
    assert _ref_lowmargin("suan", None, "abstain", _t("𮅕", 0.5, "abstain:slot"), "𮅕", f)[0] is None  # 别的弃权原因


def test_registered_groups():
    for g, form in {"suan": "𮅕", "qi": "竒", "pai": "𣲖", "shang": "尙", "sang": "䘮"}.items():
        fl = GROUPS[g].flow
        assert fl.ref_margin > 0 and fl.ref_margin_forms == form and form in GROUPS[g].members


# —— 同批：勅敕 整理本缺字 〓 不再拦、蒙𫎇 坐标对位 䝉（同字另一写法）不拦（A24 2026-11-01）
from dataclasses import dataclass, field

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.groups import flow
from open_guji_cv.groups.flow import FlowConfig, group_flow_pass
from open_guji_cv.groups.protocol import GroupVerdict


@dataclass
class _Rec:
    id: str
    char: str | None = None
    admit: bool = False
    channel: str | None = None
    provenance: str = ""
    doubts: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


def _lift(monkeypatch, g, pick, margin, coord, cands):
    monkeypatch.setattr(flow, "_solve", lambda name, *a, **k: GroupVerdict(pick, conf=margin, why="agree", via=name, extra={"margin": margin}))
    r = _Rec("x")
    group_flow_pass([r], {}, lambda cid: cands, lambda r: False, FlowConfig(groups=(g,)), veto_refs={"x": coord})
    return r


def test_chi_gap_coord_lifts(monkeypatch):
    r = _lift(monkeypatch, "chi", "勅", 0.9, "〓", [("敕", 0.983), ("勅", 0.97)])
    assert r.admit and r.char == "勅"


def test_chi_outside_coord_still_blocks(monkeypatch):
    r = _lift(monkeypatch, "chi", "勅", 0.9, "勍", [("敕", 0.983), ("勅", 0.97)])
    assert not r.admit and "group_flow_coord_dissent" in r.doubts


def test_mn_variant_writing_coord_lifts_but_other_char_blocks(monkeypatch):
    c = [("𫎇", 0.97), ("蒙", 0.965)]
    assert _lift(monkeypatch, "mn", "𫎇", 0.9, "䝉", c).admit
    r = _lift(monkeypatch, "mn", "𫎇", 0.9, "𪷟", c)           # 𪷟 是 濛，另一个字
    assert not r.admit and "group_flow_coord_dissent" in r.doubts
