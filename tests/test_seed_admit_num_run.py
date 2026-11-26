"""seed_admit 无参照格「数字串里的数字」放过 never_match 护栏（`SeedAdmitParams.num_run_cov`，缺省关）。

实例取自全唐文 001 front3（形近字线 11-08 看图）：姓氏韻編卷数小注「八四百五【四】百」，库 四 0.997、田 0.955，
匹配器因 四/因 在形近护栏表里判 never_match → 无参照页全进待审。
"""
from __future__ import annotations

import pytest

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_decision, page_match, write_product
from open_guji_cv.core.engine import params_hash
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.seed_admit import SeedAdmitParams, SeedAdmitStep, num_run_decide

BOOK, PAGE, COL = "tbook", 1, 1
ON = {"num_run_cov": 0.995}
NM = ["护栏:never_match", "库 unsure(cov=0.997)", "上下文 margin 不足(0.02)", "near_form"]


def _rec(slot, cands, guard=None, verdict="unsure"):
    return dict(slot=slot, verdict=verdict, char=None, cov=cands[0][1], wmax=16.0, guard=guard, candidates=list(cands))


def _run(tmp_path, monkeypatch, recs, params=None):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, col=COL, recs=recs))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[dict(slot=r["slot"], char=None, margin=0.0, source="prior") for r in recs]))
    ctx.params["seed_admit"] = SeedAdmitParams(**{"patch_missing": "skip", **(params or {})})
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    return {r.slot: r for r in col.chars}


RUN = [_rec(1, (("五", 0.999),)),
       _rec(2, (("四", 0.997), ("田", 0.955)), guard="never_match"),
       _rec(3, (("百", 0.999),))]


def test_params_off_is_invisible():
    off, on = SeedAdmitParams(), SeedAdmitParams(**ON)
    assert not [k for k in off.model_dump() if k.startswith("num_run")]
    assert {k for k in on.model_dump() if k.startswith("num_run")} == {"num_run_cov", "num_run_gap"}
    sp, pt = SeedAdmitStep.spec.soft_params, SeedAdmitStep.spec.path_params
    assert params_hash(on, sp, pt) != params_hash(off, sp, pt)


def test_off_leaves_digit_in_review(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, RUN)[2]
    assert not r.admit


def test_on_admits_digit_in_run(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, RUN, ON)[2]
    assert r.admit and r.channel == "match_num_run" and r.char == "四" and r.doubts == []
    assert r.evidence["no_glyph_lib"] is True and r.evidence["num_run"]["gap"] == pytest.approx(0.042)


def test_lone_digit_stays(tmp_path, monkeypatch):
    """前后都不是数字（人名「房千里」一类）→ 不放。"""
    recs = [_rec(1, (("房", 0.999),)), _rec(2, (("千", 0.998), ("干", 0.9)), guard="never_match"),
            _rec(3, (("里", 0.999),))]
    assert not _run(tmp_path, monkeypatch, recs, ON)[2].admit


KW = dict(cov_min=0.995, gap_min=0.01, are_variants=lambda a, b: False)


@pytest.mark.parametrize("kw", [
    dict(cands=[("四", 0.997), ("田", 0.955)], guard="timeout", doubts=NM, prev="五", nxt=None),     # timeout 不碰
    dict(cands=[("七", 0.997), ("士", 0.9)], guard=None, doubts=["context_page_end", "near_form"],
         prev="五", nxt=None),                                                                       # 页末疑问照拦
    dict(cands=[("十", 0.9881), ("卜", 0.9874)], guard=None, doubts=["库 unsure", "group_flow_abstain"],
         prev="百", nxt=None),                                                                       # 001:162:3:20a 领先不够
    dict(cands=[("九", 0.999), ("丸", 0.995)], guard=None, doubts=["库 same 但准入被拦"], prev="十", nxt=None),
    dict(cands=[("四", 0.997), ("田", 0.955)], guard="conflict", doubts=NM, prev="五", nxt=None),    # conflict 不碰
    dict(cands=[("王", 0.998), ("玉", 0.9)], guard="never_match", doubts=NM, prev="五", nxt=None),   # 不是数字
    dict(cands=[("七", 0.994), ("士", 0.9)], guard="never_match", doubts=NM, prev="五", nxt=None),   # cov 不到
    dict(cands=[("七", 0.998), ("士", 0.992)], guard="never_match", doubts=NM, prev="五", nxt=None),  # 领先不够
    dict(cands=[("八", 0.997), ("入", 0.968)], guard="never_match", doubts=NM + ["group_flow_conflict"],
         prev="五", nxt=None),                                                                       # 别的疑问
    dict(cands=[("六", 0.997), ("大", 0.9)], guard="never_match", doubts=NM, prev=None, nxt=None),   # 无数字邻格
])
def test_decide_blocks(kw):
    assert num_run_decide(**kw, **KW) is None


def test_decide_admits():
    assert num_run_decide(cands=[("七", 0.998), ("士", 0.94), ("匕", 0.0)], guard="never_match", doubts=NM,
                          prev=None, nxt="百", **KW) == ("七", 0.998, 0.058)


def test_decide_admits_unguarded_near_form_ten():
    """001:70:6:4b「【十】七十六十」：库 same 十 0.9992，near_form＋字组弃权挡下，没判护栏。"""
    ds = ["库 same 但准入被拦", "near_form", "group_flow_abstain"]
    assert num_run_decide(cands=[("十", 0.9992), ("卜", 0.9615), ("七", 0.9584)], guard=None, doubts=ds,
                          prev=None, nxt="七", **KW) == ("十", 0.9992, 0.0377)


JUAN = dict(cands=[("卷", 0.968), ("春", 0.94)], guard=None, doubts=["库 unsure(cov=0.968)", "上下文 margin 不足(0.02)",
                                                                     "group_flow_abstain"])


def test_juan_before_digits():
    """002:41:9:2「【卷】一百六」：库 卷 0.968，后一格是数字 → 开 num_run_juan_cov 才放。"""
    assert num_run_decide(**JUAN, prev=None, nxt="一", **KW) is None
    assert num_run_decide(**JUAN, prev=None, nxt="一", juan_cov=0.95, **KW) == ("卷", 0.968, 0.028)
    assert num_run_decide(**JUAN, prev="一", nxt=None, juan_cov=0.95, **KW) is None      # 只认后一格
    assert num_run_decide(**JUAN, prev=None, nxt="一", juan_cov=0.97, **KW) is None      # cov 不到


def test_juan_param_invisible_when_unset():
    assert "num_run_juan_cov" not in SeedAdmitParams(num_run_cov=0.995).model_dump()
    assert SeedAdmitParams(num_run_cov=0.995, num_run_juan_cov=0.95).model_dump()["num_run_juan_cov"] == 0.95


def test_pass_admits_juan(tmp_path, monkeypatch):
    recs = [_rec(1, (("卷", 0.968), ("春", 0.94))), _rec(2, (("一", 0.999),)), _rec(3, (("百", 0.999),))]
    assert not _run(tmp_path, monkeypatch, recs, ON)[1].admit
    r = _run(tmp_path, monkeypatch, recs, {**ON, "num_run_juan_cov": 0.95})[1]
    assert r.admit and r.channel == "match_num_run" and r.char == "卷" and r.evidence["num_run"]["next"] == "一"


def test_cov_5b_pure():
    from open_guji_cv.steps.seed_admit import num_run_decide
    kw = dict(guard="never_match", doubts=["near_form"], prev="十", nxt=None, cov_min=0.995, gap_min=0.01,
              are_variants=lambda a, b: False)
    cands = [("六", 0.988), ("大", 0.952)]
    assert num_run_decide(cands=cands, **kw) is None
    assert num_run_decide(cands=cands, rare_top="六", cov_5b=0.97, gap_5b=0.02, **kw) == ("六", 0.988, 0.036)
    assert num_run_decide(cands=cands, rare_top="大", cov_5b=0.97, gap_5b=0.02, **kw) is None   # 5-b 不同意
    assert num_run_decide(cands=[("六", 0.988), ("大", 0.975)], rare_top="六", cov_5b=0.97, gap_5b=0.02, **kw) is None
    assert num_run_decide(cands=cands, rare_top="六", cov_5b=0.97, gap_5b=0.02, **{**kw, "prev": None}) is None
    # 够原门槛的格照原规则（领先 0.01），不被 gap_5b 收紧（front7 001:181:4:6a 十 0.9995 领先 0.019）
    hi = [("十", 0.9995), ("七", 0.9801)]
    assert num_run_decide(cands=hi, rare_top="十", cov_5b=0.97, gap_5b=0.02, **kw) == ("十", 0.9995, 0.0194)


def test_cov_5b_gated_optional_upstream():
    from open_guji_cv.core.spec import live_optional_consumes
    from open_guji_cv.steps.seed_admit import SeedAdmitStep
    assert "rare_candidates" in live_optional_consumes(SeedAdmitStep.spec,
                                                       SeedAdmitParams(num_run_cov=0.995, num_run_cov_5b=0.97))
