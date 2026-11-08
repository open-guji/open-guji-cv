"""seed_admit 无参照格「按字自适应门槛」（`SeedAdmitParams.solo_adapt_pct`，缺省关）。

实例取自全唐文 001–003（形近字线 11-08 看图）：
- 「張」自比 p10 约 0.965，0.97 的格该放（旧 0.98 一刀切卡住）；
- 001:126:4:3 刻「皓」，库首位 浩 0.949，5-b 首位 皓（are_variants 认 皓／浩 为异体）→ 必须不放；
- 治／洽 自动算出的高危字对：对手在窗口内 → 不放。
"""
from __future__ import annotations

import json

import pytest

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_decision, page_match, write_product
from open_guji_cv.core.engine import params_hash
from open_guji_cv.core.spec import live_optional_consumes
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.kinds.recog import ColumnRare, PageRare, RareCand, RareRec
from open_guji_cv.steps.seed_admit import (SeedAdmitParams, SeedAdmitStep, load_adapt_profile,
                                           solo_adapt_decide)

BOOK, PAGE, COL = "tbook", 1, 1
PROF = {"schema": "char_cov_profile/1",
        "prof": {"張": {"n": 30, "miss": 0.0, "p10": 0.965, "p25": 0.972, "med": 0.978},
                 "浩": {"n": 10, "miss": 0.0, "p10": 0.94, "p25": 0.95, "med": 0.97},
                 "治": {"n": 10, "miss": 0.0, "p10": 0.955, "p25": 0.96, "med": 0.983},
                 "丸": {"n": 2, "miss": 0.0, "p10": 0.95, "p25": 0.96, "med": 0.97}},
        "cross": {"張|振": 0.95, "治|洽": 0.99},
        "risk": [["治", "洽"]]}
OK_DOUBTS = ["库 unsure(cov=0.970)", "上下文 margin 不足(0.02)"]


@pytest.fixture()
def prof_path(tmp_path):
    p = tmp_path / "char_cov_profile.json"
    p.write_text(json.dumps(PROF, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _kw(prof_path, **over):
    P = load_adapt_profile(prof_path)
    kw = dict(guard=None, doubts=OK_DOUBTS, prof=P["prof"], cross=P["cross"], risk=P["risk"], pct="p10",
              floor=0.94, gap_min=0.01, min_n=5, window=0.05, are_variants=lambda a, b: {a, b} == {"皓", "浩"},
              group_chars=frozenset("己已巳"), near_form_chars=frozenset("士土"))
    kw.update(over)
    return kw


def test_decide_admits_dense_char(prof_path):
    assert solo_adapt_decide(cands=[("張", 0.970), ("振", 0.93)], rare_top="張", **_kw(prof_path)) == ("張", 0.97, 0.04)


@pytest.mark.parametrize("cands,rare,over", [
    ([("張", 0.962), ("振", 0.90)], "張", {}),                         # 低于本字自比 p10
    ([("張", 0.970), ("振", 0.90)], "張", {"pct": "p25"}),             # p25 档更严
    ([("浩", 0.949), ("結", 0.9355)], "皓", {}),                        # 5-b 首位是异体也不认（001:126:4:3）
    ([("治", 0.975), ("洽", 0.94)], "治", {}),                          # 高危字对在窗口内
    ([("張", 0.970), ("振", 0.958)], "張", {}),                         # 本格像 振 超过 張 刻例像 振 的上限
    ([("張", 0.970), ("長", 0.93)], "張", {}),                          # 長 没进字表（< 0.90）却 0.93 → 不放
    ([("丸", 0.99), ("九", 0.90)], "丸", {}),                           # 自比样本太少
    ([("張", 0.970), ("振", 0.90)], "張", {"guard": "never_match"}),
    ([("張", 0.970), ("振", 0.90)], "張", {"doubts": ["near_form"]}),
    ([("張", 0.970), ("振", 0.90)], None, {}),
])
def test_decide_blocks(prof_path, cands, rare, over):
    assert solo_adapt_decide(cands=cands, rare_top=rare, **_kw(prof_path, **over)) is None


def test_params_off_is_invisible(prof_path):
    off = SeedAdmitParams()
    assert not [k for k in off.model_dump() if k.startswith("solo_adapt")]
    on = SeedAdmitParams(solo_adapt_pct="p10", solo_adapt_profile=prof_path)
    sp, pt = SeedAdmitStep.spec.soft_params, SeedAdmitStep.spec.path_params
    assert params_hash(on, sp, pt) != params_hash(off, sp, pt)
    assert on.solo_adapt_fingerprint and on.solo_adapt_fingerprint != "missing"
    assert "rare_candidates" in live_optional_consumes(SeedAdmitStep.spec, on)
    with pytest.raises(ValueError):
        SeedAdmitParams(solo_adapt_pct="p50", solo_adapt_profile=prof_path)


def _run(tmp_path, monkeypatch, prof_path, params):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[dict(slot=1, verdict="unsure", char=None, cov=0.97, wmax=16.0, guard=None,
                                         candidates=[("張", 0.97), ("振", 0.93)])]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[dict(slot=1, char=None, margin=0.0, source="prior")]))
    write_product(ctx, "rare_candidates", PAGE, rare_candidates=PageRare(page=PAGE, columns=[ColumnRare(
        col=COL, ok=True, chars=[RareRec(id=f"{BOOK}:{PAGE}:{COL}:1", slot=1,
                                         candidates=[RareCand(char="張", score=0.97, font="emb")])])]))
    ctx.params["seed_admit"] = SeedAdmitParams(patch_missing="skip", **params)
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    (r,) = col.chars
    return r


def test_pass_off_and_on(tmp_path, monkeypatch, prof_path):
    assert not _run(tmp_path, monkeypatch, prof_path, {}).admit
    r = _run(tmp_path, monkeypatch, prof_path, {"solo_adapt_pct": "p10", "solo_adapt_profile": prof_path})
    assert r.admit and r.channel == "match_solo_adapt" and r.char == "張"
    assert r.evidence["no_glyph_lib"] is True and r.evidence["solo_adapt"]["self"] == 0.965


def test_missing_profile_admits_nothing(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, "", {"solo_adapt_pct": "p10", "solo_adapt_profile": str(tmp_path / "nope.json")})
    assert not r.admit


def test_builder_aggregate():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("ccp", Path(__file__).resolve().parents[1] / "scripts" / "char_cov_profile.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    recs = [{"c": "治", "cands": [["治", 0.98], ["洽", 0.99]]}] + [{"c": "治", "cands": [["治", 0.97 + i / 1000]]} for i in range(5)]
    out = mod.aggregate(recs)
    assert out["schema"] == "char_cov_profile/1" and out["prof"]["治"]["n"] == 6
    assert ["治", "洽"] in out["risk"] and out["cross"]["治|洽"] == 0.99


# ── front7 三档（solo_adapt_risk_gap、solo_adapt_abstain_ok；num_run_cov_5b 见 test_seed_admit_num_run）──


def test_risk_gap_lets_far_risk_rival_pass(prof_path):
    kw = dict(cands=[("治", 0.975), ("洽", 0.94)], rare_top="治")
    assert solo_adapt_decide(**kw, **_kw(prof_path)) is None
    assert solo_adapt_decide(**kw, **_kw(prof_path, risk_gap=0.02)) == ("治", 0.975, 0.035)
    # 落后不够 risk_gap 的高危对手照拦
    assert solo_adapt_decide(cands=[("治", 0.975), ("洽", 0.96)], rare_top="治", **_kw(prof_path, risk_gap=0.02)) is None


def test_abstain_ok_only_for_non_group_top(prof_path):
    dz = OK_DOUBTS + ["group_flow_abstain"]
    kw = dict(cands=[("張", 0.970), ("振", 0.93)], rare_top="張")
    assert solo_adapt_decide(**kw, **_kw(prof_path, doubts=dz)) is None
    assert solo_adapt_decide(**kw, **_kw(prof_path, doubts=dz, abstain_ok=True)) == ("張", 0.97, 0.04)
    assert solo_adapt_decide(**kw, **_kw(prof_path, doubts=dz, abstain_ok=True, abstain_skip="真張")) is None
    assert solo_adapt_decide(**kw, **_kw(prof_path, doubts=dz, abstain_ok=True, group_chars=frozenset("張"))) is None


def test_front7_params_invisible_when_off():
    d = SeedAdmitParams(solo_adapt_pct="p10").model_dump()
    for k in ("solo_adapt_risk_gap", "solo_adapt_abstain_ok", "solo_adapt_abstain_skip", "num_run_cov_5b", "num_run_gap_5b"):
        assert k not in d
    d = SeedAdmitParams(solo_adapt_pct="p10", solo_adapt_risk_gap=0.02, solo_adapt_abstain_ok=True,
                        solo_adapt_abstain_skip="真").model_dump()
    assert d["solo_adapt_risk_gap"] == 0.02 and d["solo_adapt_abstain_skip"] == "真"
