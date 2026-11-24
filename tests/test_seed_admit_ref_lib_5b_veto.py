"""seed_admit 「整理本＝库首位」放行的 5-b 否决（`ref_lib_5b_veto`），缺省关。"""
from __future__ import annotations

from types import SimpleNamespace as NS

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.steps.seed_admit import (SeedAdmitParams, _ref_lib_5b_veto_pass,
                                           ref_lib_5b_veto_decide)


def test_decide():
    # 殿本 vol20 41:6:18：整理本 霍＝库首位 霍，5-b 首位 靃 0.973、领先 0.028 → 否决
    assert ref_lib_5b_veto_decide("霍", [("靃", 0.973), ("雥", 0.9445), ("靍", 0.9421)], 0.95, 0.02) == ("靃", 0.973, 0.0285)
    # 5-b 同意、分不够、领先不够、首位非汉字：不否决
    assert ref_lib_5b_veto_decide("懷", [("懷", 0.973), ("懐", 0.95)], 0.95, 0.02) is None
    assert ref_lib_5b_veto_decide("霍", [("靃", 0.949), ("雥", 0.90)], 0.95, 0.02) is None
    assert ref_lib_5b_veto_decide("隠", [("隱", 0.96), ("隠", 0.955)], 0.95, 0.02) is None
    assert ref_lib_5b_veto_decide("一", [("—", 0.99), ("二", 0.90)], 0.95, 0.02) is None
    assert ref_lib_5b_veto_decide("霍", [], 0.95, 0.02) is None


def _rec(cid, ch, channel="ref_lib", admit=True):
    return NS(id=cid, char=ch, channel=channel, admit=admit, provenance="match", doubts=[], evidence={})


def test_pass_only_touches_ref_lib():
    a, b, c = _rec("v:1:1:1", "霍"), _rec("v:1:1:2", "霍", channel="match_ref"), _rec("v:1:1:3", "懷")
    out = [NS(chars=[a, b, c])]
    cand = lambda ch, s: NS(char=ch, score=s)
    rare = NS(columns=[NS(chars=[NS(id="v:1:1:1", candidates=[cand("靃", 0.97), cand("雥", 0.94)]),
                                 NS(id="v:1:1:2", candidates=[cand("靃", 0.97), cand("雥", 0.94)]),
                                 NS(id="v:1:1:3", candidates=[cand("懷", 0.97), cand("懐", 0.94)])])])
    p = SeedAdmitParams(ref_lib_5b_veto=0.95)
    assert _ref_lib_5b_veto_pass(p, out, rare) == 1
    assert a.admit is False and a.channel is None and "ref_lib_5b_veto" in a.doubts
    assert a.evidence["ref_lib_5b_veto"]["rare"] == "靃"
    assert b.admit and c.admit
    assert _ref_lib_5b_veto_pass(p, out, None) == 0


def test_dump_off_by_default():
    d = SeedAdmitParams().model_dump()
    assert "ref_lib_5b_veto" not in d and "ref_lib_5b_veto_lead" not in d
    d2 = SeedAdmitParams(ref_lib_5b_veto=0.95).model_dump()
    assert d2["ref_lib_5b_veto"] == 0.95 and d2["ref_lib_5b_veto_lead"] == 0.02
