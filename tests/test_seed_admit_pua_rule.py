# -*- coding: utf-8 -*-
"""Step7 整理本缺字特殊规则（`pua_rules`，通道 `pua_rule`）：整理本写 〓、库首位在人定的刻形表里 → 按表录字。

直接测页末那一遍 `_pua_rule_pass`，数据全是自造的。"""
from __future__ import annotations

from types import SimpleNamespace as NS

from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _parse_pua_rules, _pua_rule_pass

B = "tbook:1"


def _page(pending: dict):
    """一列三格：`pending={slot: dict(...)}` 的格待审，其余已放行。"""
    recs = []
    for i in range(1, 4):
        if i in pending:
            pd = pending[i]
            recs.append(AdmitRec(id=f"{B}:1:{i}", slot=i, admit=False, char=pd.get("char"),
                                 doubts=list(pd.get("doubts", [])), channel=pd.get("channel"),
                                 provenance=pd.get("provenance", "")))
        else:
            recs.append(AdmitRec(id=f"{B}:1:{i}", slot=i, admit=True, channel="match_ref", char="之"))
    return [ColumnAdmit(col=1, chars=recs)]


def _mm(lib: dict):
    """{slot: (字, cov[, verdict, guard])}"""
    out = {}
    for s, v in lib.items():
        ch, cov, verdict, guard = (list(v) + [None, None])[:4]
        out[f"{B}:1:{s}"] = NS(char=None, candidates=[(ch, cov)], verdict=verdict or "unsure", guard=guard)
    return out


def _run(pending, lib, coord=None, amap=None, **params):
    params.setdefault("pua_rules", "絃,確,埀=垂,點=㸃")
    p = SeedAdmitParams(db_path="x", **params)
    out = _page(pending)
    n = _pua_rule_pass(p, out, _mm(lib), amap or {}, {f"{B}:1:{s}": c for s, c in (coord or {}).items()})
    return n, {r.slot: r for r in out[0].chars}


def test_parse_rules():
    assert _parse_pua_rules("絃, 確 ,埀=垂,點=㸃,,ab") == {"絃": "絃", "確": "確", "埀": "垂", "點": "㸃"}
    assert _parse_pua_rules("") == {}


def test_admits_by_table_with_mapping():
    n, r = _run({1: {}, 2: {}}, {1: ("絃", 0.93), 2: ("點", 0.97)}, coord={1: "〓", 2: "〓"})
    assert n == 2
    assert (r[1].admit, r[1].channel, r[1].char) == (True, "pua_rule", "絃")
    assert r[2].char == "㸃" and r[2].evidence["lane"]["lib"] == "點"
    assert r[1].doubts == ["lane_pua_rule"]


def test_needs_pua_ref():
    """整理本有字（不是 〓）就不归这条管；没有坐标对位时看现役对位字。"""
    n, _ = _run({1: {}}, {1: ("確", 0.95)}, coord={1: "確"})
    assert n == 0
    n, _ = _run({1: {}}, {1: ("確", 0.95)}, amap={f"{B}:1:1": ("〓", "replace")})
    assert n == 1
    n, _ = _run({1: {}}, {1: ("確", 0.95)})
    assert n == 0


def test_lib_not_in_table_or_low_cov_or_guarded():
    n, _ = _run({1: {}, 2: {}, 3: {}},
                {1: ("鉉", 0.99), 2: ("確", 0.80), 3: ("確", 0.95, "unsure", "conflict")},
                coord={1: "〓", 2: "〓", 3: "〓"})
    assert n == 0
    n, _ = _run({1: {}}, {1: ("確", 0.95, "diff")}, coord={1: "〓"})
    assert n == 0


def test_skips_human_excluded_occluded_hard():
    pend = {1: {"provenance": "human"}, 2: {"doubts": ["excluded"]}, 3: {"doubts": ["occluded"]}}
    n, _ = _run(pend, {s: ("確", 0.95) for s in (1, 2, 3)}, coord={s: "〓" for s in (1, 2, 3)})
    assert n == 0
    n, _ = _run({1: {"doubts": ["group_flow_disagree"]}}, {1: ("確", 0.95)}, coord={1: "〓"})
    assert n == 0


def test_empty_table_is_off_and_not_in_dump():
    n, _ = _run({1: {}}, {1: ("確", 0.95)}, coord={1: "〓"}, pua_rules="")
    assert n == 0
    d = SeedAdmitParams(db_path="x").model_dump()
    assert "pua_rules" not in d and "pua_rule_cov" not in d
    d = SeedAdmitParams(db_path="x", pua_rules="確").model_dump()
    assert d["pua_rules"] == "確" and d["pua_rule_cov"] == 0.85
