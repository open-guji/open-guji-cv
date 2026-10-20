# -*- coding: utf-8 -*-
"""日曰 字形宽高比（`open_guji_cv/groups/aspect.py`）与它在 group_flow 里当第二路的接线。自造字块图。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.groups import aspect


def _ri(w, h, pad=20):
    """白底，黑色方框 宽 w 高 h（像素），像「日／曰」的外框。"""
    g = np.full((h + 2 * pad, w + 2 * pad), 255, np.uint8)
    g[pad:pad + h, pad:pad + w] = 0
    g[pad + 6:pad + h - 6, pad + 6:pad + w - 6] = 255
    g[pad + h // 2 - 3:pad + h // 2 + 3, pad + 6:pad + w - 6] = 0
    return g


def test_aspect_picks_narrow_ri_and_wide_yue():
    assert aspect.judge(_ri(60, 100))[0] == "日"      # 0.60
    assert aspect.judge(_ri(95, 100))[0] == "曰"      # 0.95
    assert aspect.judge(_ri(78, 100))[0] is None      # 中间弃权


def test_aspect_no_glyph_abstains():
    assert aspect.judge(np.full((80, 80), 255, np.uint8)) == (None, None)


def test_ry_flow_demotes_on_strong_shape_conflict(monkeypatch):
    from dataclasses import dataclass, field
    from open_guji_cv.groups import flow
    from open_guji_cv.groups.flow import FlowConfig, group_flow_pass
    from open_guji_cv.groups.protocol import GroupVerdict

    @dataclass
    class Rec:
        id: str
        char: str | None = None
        admit: bool = False
        channel: str | None = None
        provenance: str = ""
        doubts: list = field(default_factory=list)
        evidence: dict = field(default_factory=dict)

    picks = {"ctx": "曰", "ry_shape": "日"}
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(picks[name], via=name))
    r = Rec("b", "曰", True, "match_ref", "match")
    group_flow_pass([r], {}, lambda cid: [], lambda r: False, FlowConfig(groups=("ry",)))
    assert not r.admit and "group_flow_disagree" in r.doubts
