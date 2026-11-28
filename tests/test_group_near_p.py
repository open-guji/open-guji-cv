# -*- coding: utf-8 -*-
"""NearP（`groups/methods.py`）：第三步收尾给的组内校准概率进字组流程（官宫，Sheldon 2026-11-26）。自造数据。"""
from __future__ import annotations

from open_guji_cv.groups.registry import FLOW_GROUPS as GROUPS
from open_guji_cv.groups import methods as M
from open_guji_cv.groups.flow import FlowConfig, decide


def _inp(near_p, thr, cell="v:1:1:1"):
    cfg = FlowConfig(groups=("guan",), near_p={cell: near_p} if near_p is not None else {},
                     near_p_min={"guan": thr} if thr is not None else {})
    return M.MethodInput(group="guan", members=GROUPS["guan"].members, cell_id=cell, cands=[], ref=None, cfg=cfg)


def test_high_p_gives_char_low_p_abstains():
    v = M.NEAR_P.run(_inp({"官": 0.01, "宫": 0.99}, 0.98))
    assert v.char == "宫" and v.why == "agree" and v.conf == 0.99 and v.extra["p"]["宫"] == 0.99
    v = M.NEAR_P.run(_inp({"官": 0.30, "宫": 0.70}, 0.98))
    assert v.char is None and v.why == "abstain:low_p"


def test_no_p_or_not_enabled_abstains_and_none_p_ignored():
    assert M.NEAR_P.run(_inp(None, 0.98)).why == "abstain:no_p"
    assert M.NEAR_P.run(_inp({"官": 0.2, "宫": 0.99}, None)).why == "abstain:no_p"
    v = M.NEAR_P.run(_inp({"宫": 0.99, "宮": None}, 0.98))       # 宮 p=None（异体，记 same_as 宫）不参与
    assert v.char == "宫"


def test_guan_methods_and_decide_skips_near_p_when_not_enabled():
    assert GROUPS["guan"].flow.solvers == ("near_p", "ctx")
    cfg = FlowConfig(groups=("guan",))
    r = type("R", (), {"id": "v:1:1:1", "char": "官"})()
    ch, why, trail = decide("guan", r, [("官", 0.9)], None, cfg)
    assert all(t["solver"] != "near_p" for t in trail)            # 没开 → 留痕不出现，别的书产物不变


def test_per_char_threshold():
    thr = {"宫": 0.955, "官": 0.999}
    assert M.NEAR_P.run(_inp({"官": 0.01, "宫": 0.96}, thr)).char == "宫"
    assert M.NEAR_P.run(_inp({"官": 0.98, "宫": 0.02}, thr)).why == "abstain:low_p"      # 官 没到 0.999
    assert M.NEAR_P.run(_inp({"官": 0.9995, "宫": 0.0005}, thr)).char == "官"
    assert M.NEAR_P.run(_inp({"官": 0.2, "宫": 0.99}, {"官": 0.9})).why == "abstain:low_p"   # 没列的字不放
