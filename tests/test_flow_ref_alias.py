"""字组流程书级整理本字别名 `group_flow_ref_alias`（全唐文 間→閒，11-20）。"""
from __future__ import annotations

from types import SimpleNamespace

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.groups import flow as F
from open_guji_cv.steps.seed_admit import SeedAdmitParams


def _run(monkeypatch, alias):
    seen = {}

    def fake_entry(r, cands, ref, cfg, canon, coord_ref=None):
        seen[r.id] = (ref, coord_ref)
        return None
    monkeypatch.setattr(F, "entry", fake_entry)
    seq = [SimpleNamespace(id="a"), SimpleNamespace(id="b"), SimpleNamespace(id="c")]
    amap = {"a": ("間", "="), "b": ("聞", "="), "c": (None, None)}
    cfg = F.FlowConfig(groups=("men",), ref_alias=alias)
    F.group_flow_pass(seq, amap, lambda i: [], lambda r: False, cfg, veto_refs={"c": "間"})
    return seen, amap


def test_alias_maps_ref_and_coord(monkeypatch):
    seen, amap = _run(monkeypatch, {"間": "閒"})
    assert seen["a"] == ("閒", None)
    assert seen["b"] == ("聞", None)
    assert seen["c"] == (None, "閒")
    assert amap["a"] == ("間", "=")              # 调用方的 amap 不被改


def test_no_alias_unchanged(monkeypatch):
    seen, _ = _run(monkeypatch, {})
    assert seen["a"] == ("間", None) and seen["c"] == (None, "間")


def test_param_default_off_and_hidden():
    p = SeedAdmitParams()
    assert p.group_flow_ref_alias == {}
    assert "group_flow_ref_alias" not in p.model_dump()
    assert SeedAdmitParams(group_flow_ref_alias={"間": "閒"}).model_dump()["group_flow_ref_alias"] == {"間": "閒"}
