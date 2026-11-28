"""vis3 影子读口：对比口径、只写 evidence、不改放行（CV4 2026-11-28）。"""
from types import SimpleNamespace as NS

from open_guji_cv.steps.seed_admit_vis3 import compare, cur_vis, vis3_of, vis3_shadow_pass


def _ev(why, **kw):
    return {"group": {"solvers": [{"solver": "vis", "char": None, "why": why, **kw}]}}


def test_cur_vis_parse():
    assert cur_vis(_ev("high:曰")) == {"src": "L4", "char": "曰", "conf": "high", "ask": False}
    assert cur_vis(_ev("ref_dissent:日", vis_conf="high"))["char"] == "日"
    assert cur_vis(_ev("x", ask={"ver": 1}))["ask"] is True
    assert cur_vis({"vis_ruling": {"char": "己", "conf": "high"}})["src"] == "ruling"
    assert cur_vis({}) is None


def test_compare():
    cur = cur_vis(_ev("high:曰"))
    mk = lambda **k: vis3_of({"status": "hit", "char": None, "other": False, **k})
    assert compare(cur, mk(char="曰")) == "same"
    assert compare(cur, mk(char="日")) == "diff"
    assert compare(cur, vis3_of({"status": "pending"})) == "cur_only"
    assert compare(cur, None) == "cur_only"
    assert compare(None, mk(char="日")) == "vis3_only"
    assert compare(None, None) is None
    assert compare(cur_vis(_ev("high:")), mk(other=True)) == "same"


def test_pass_only_writes_evidence():
    r1 = NS(id="a", evidence=_ev("high:曰"), char="曰", admit=True)
    r2 = NS(id="b", evidence={}, char="x", admit=False)
    out = [NS(chars=[r1, r2])]
    fin = NS(by_id=lambda: {"a": NS(vis={"status": "hit", "char": "日", "other": False})})
    cnt = vis3_shadow_pass(fin, out)
    assert cnt == {"diff": 1}
    assert r1.evidence["vis3_shadow"]["cmp"] == "diff" and (r1.char, r1.admit) == ("曰", True)
    assert "vis3_shadow" not in r2.evidence
    assert vis3_shadow_pass(None, [NS(chars=[r1])]) == {"cur_only": 1}
