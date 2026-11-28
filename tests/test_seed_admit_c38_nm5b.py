"""seed_admit `group_flow_pair_shape_nm_5b`（never_match 格 5-b 首位在这一对里也交两字刻形判）与
`solo_cal_5b_canon`（solo_cal 5-b 档按码位归一后比），都缺省关。"""
from __future__ import annotations

from types import SimpleNamespace as NS

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.steps import seed_admit as sa
from open_guji_cv.steps.seed_admit import SeedAdmitParams


def test_dump_off_by_default():
    d = SeedAdmitParams().model_dump()
    assert "group_flow_pair_shape_nm_5b" not in d and "solo_cal_5b_canon" not in d
    d2 = SeedAdmitParams(group_flow_pair_shape_nm_5b=True, solo_cal_5b_canon=True).model_dump()
    assert d2["group_flow_pair_shape_nm_5b"] is True and d2["solo_cal_5b_canon"] is True


def _rec(cid, ch, guard, doubts):
    return NS(id=cid, char=ch, admit=False, channel=None, provenance="", slot=1, sub=None,
              doubts=list(doubts), evidence={"guard": guard})


def _pair_run(monkeypatch, nm_5b):
    monkeypatch.setattr("open_guji_cv.groups.pair_shape.load", lambda path: {"chars": ["王", "玉"]})
    monkeypatch.setattr("open_guji_cv.groups.pair_shape.judge", lambda img, model: {"char": "王", "why": "agree", "score": 3.0})
    monkeypatch.setattr(sa, "_page_patch", lambda *a, **k: object())
    recs = [_rec("001:1:1:1", "王", "never_match", ["库 unsure(cov=0.97)", "护栏:never_match"]),
            _rec("001:1:1:2", "王", "never_match", ["库 unsure(cov=0.97)", "护栏:never_match"])]
    out = [NS(col=1, chars=recs)]
    n = sa._pair_shape_pass(SeedAdmitParams(), out, {}, None, 1, {}, {}, model_path="x", nm_5b=nm_5b)
    return n, recs


def test_pair_shape_nm_off_keeps_never_match(monkeypatch):
    n, recs = _pair_run(monkeypatch, None)
    assert n == 0 and not any(r.admit for r in recs)


def test_pair_shape_nm_needs_5b_in_pair(monkeypatch):
    n, recs = _pair_run(monkeypatch, {"001:1:1:1": "王", "001:1:1:2": "土"})
    assert n == 1
    assert recs[0].admit and recs[0].channel == "pair_shape" and recs[0].evidence["pair_shape"]["nm_5b"] == "王"
    assert not recs[1].admit                      # 5-b 首位是组外的土：不判


def _solo_run(canon):
    p = SeedAdmitParams(solo_cal=True, solo_cal_5b_cov=0.95, solo_cal_allow="愼")
    rec = NS(id="001:1:1:1", char="愼", admit=False, channel=None, provenance="", doubts=["库 unsure(cov=0.96)"],
             evidence={})
    rare = NS(columns=[NS(chars=[NS(id="001:1:1:1", candidates=[NS(char="慎")])])])
    mmap = {"001:1:1:1": NS(candidates=[("愼", 0.96), ("真", 0.90)], guard=None)}
    n = sa._solo_cal_pass(p, [NS(chars=[rec])], mmap, {}, rare, {}, canon=canon)
    return n, rec


def test_solo_cal_canon():
    assert _solo_run(None)[0] == 0
    n, rec = _solo_run(lambda c: {"慎": "愼"}.get(c, c))
    assert n == 1 and rec.char == "愼" and rec.channel == "match_solo_cal"
