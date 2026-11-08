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
    dict(cands=[("四", 0.997), ("田", 0.955)], guard=None, doubts=[], prev="五", nxt=None),          # 没判护栏：归别的通道
    dict(cands=[("四", 0.997), ("田", 0.955)], guard="conflict", doubts=NM, prev="五", nxt=None),    # conflict 不碰
    dict(cands=[("王", 0.998), ("玉", 0.9)], guard="never_match", doubts=NM, prev="五", nxt=None),   # 不是数字
    dict(cands=[("七", 0.994), ("士", 0.9)], guard="never_match", doubts=NM, prev="五", nxt=None),   # cov 不到
    dict(cands=[("七", 0.998), ("士", 0.992)], guard="never_match", doubts=NM, prev="五", nxt=None),  # 领先不够
    dict(cands=[("八", 0.997), ("入", 0.968)], guard="never_match", doubts=NM + ["group_flow_abstain"],
         prev="五", nxt=None),                                                                       # 别的疑问
    dict(cands=[("六", 0.997), ("大", 0.9)], guard="never_match", doubts=NM, prev=None, nxt=None),   # 无数字邻格
])
def test_decide_blocks(kw):
    assert num_run_decide(**kw, **KW) is None


def test_decide_admits():
    assert num_run_decide(cands=[("七", 0.998), ("士", 0.94), ("匕", 0.0)], guard="never_match", doubts=NM,
                          prev=None, nxt="百", **KW) == ("七", 0.998, 0.058)
