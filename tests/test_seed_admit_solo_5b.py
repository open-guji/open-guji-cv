"""seed_admit 无参照格「库首位＋5-b 作证」放行（`SeedAdmitParams.solo_5b_cov`，缺省关）。

实例取自全唐文 001/002 首跑（front1 包，形近字线 11-08 看图）：
- 001:120:9:17 刻「右」，库首位 古 0.982（第二名 舌 0.945），Paddle 也读 古，5-b 首位 右 → 必须不放；
- 002:51:5:5 刻「王」，库首位 主 0.983、第二名 王 差不到 0.01 → 必须不放；
- 丸／九：库 丸 只有 2 例（标错），刻例数下限挡住。
"""
from __future__ import annotations

import pytest

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_decision, page_match, write_product
from open_guji_cv.core.engine import params_hash
from open_guji_cv.core.spec import live_optional_consumes
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.kinds.recog import ColumnRare, PageRare, RareCand, RareRec
from open_guji_cv.steps import seed_admit as sa
from open_guji_cv.steps.seed_admit import SeedAdmitParams, SeedAdmitStep, solo_5b_decide

BOOK, PAGE, COL = "tbook", 1, 1
ON = {"solo_5b_cov": 0.98}
KEBEN = {"百": 40, "古": 30, "主": 26, "王": 50, "丸": 2, "九": 20}


def _rare(cs: list[str]) -> PageRare:
    rec = RareRec(id=f"{BOOK}:{PAGE}:{COL}:1", slot=1,
                  candidates=[RareCand(char=c, score=0.97 - 0.01 * i, font="emb") for i, c in enumerate(cs)])
    return PageRare(page=PAGE, columns=[ColumnRare(col=COL, ok=True, chars=[rec])])


def _run(tmp_path, monkeypatch, *, cands, rare, params=None, guard=None, verdict="unsure"):
    monkeypatch.setattr(sa, "_trusted_keben_counts", lambda _db, borrow=None: KEBEN)
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[dict(slot=1, verdict=verdict, char=cands[0][0] if verdict == "same" else None, cov=cands[0][1], wmax=16.0,
                                         guard=guard, candidates=list(cands))]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[dict(slot=1, char=None, margin=0.0, source="prior")]))
    if rare is not None:
        write_product(ctx, "rare_candidates", PAGE, rare_candidates=_rare(rare))
    # 无整理本的页会走 iron 量字块尺寸；测试不造字块图，按缺块跳过
    ctx.params["seed_admit"] = SeedAdmitParams(**{"patch_missing": "skip", **(params or {})})
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    (r,) = col.chars
    return r


GOOD = dict(cands=(("百", 0.985), ("白", 0.95)), rare=["百", "白"])


# ── 声明与指纹 ───────────────────────────────────────────────────────────
def test_gated_optional_upstream():
    spec = STEPS["seed_admit"].spec
    assert ("rare_candidates", "solo_5b_cov") in spec.optional_consumes_when
    on = spec.params().model_copy(update={"solo_5b_cov": 0.98})
    assert "rare_candidates" in live_optional_consumes(spec, on)


def test_params_off_is_invisible(tmp_path):
    db = str(tmp_path / "g.db")
    off = SeedAdmitParams(db_path=db)
    assert not [k for k in off.model_dump() if k.startswith("solo_5b")]
    sp, pt = SeedAdmitStep.spec.soft_params, SeedAdmitStep.spec.path_params
    on = SeedAdmitParams(db_path=db, solo_5b_cov=0.98)
    assert {k for k in on.model_dump() if k.startswith("solo_5b")} == {"solo_5b_cov", "solo_5b_gap", "solo_5b_min_n"}
    assert params_hash(on, sp, pt) != params_hash(off, sp, pt)


# ── 通道 ────────────────────────────────────────────────────────────────
def test_off_leaves_cell_in_review(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, **GOOD)
    assert not r.admit and "solo_5b" not in r.evidence


def test_admitted_cell_never_enters_glyph_lib(tmp_path, monkeypatch):
    """C4 不自喂：match_solo_5b 放行的格带 evidence.no_glyph_lib，扫尾入库不收。"""
    r = _run(tmp_path, monkeypatch, params=ON, **GOOD)
    assert r.admit and r.channel == "match_solo_5b" and r.evidence["no_glyph_lib"] is True


def test_trusted_counts_missing_db_is_empty(tmp_path):
    """库读不了＝空表＝通道不放（宁缺勿滥）。"""
    assert sa._trusted_keben_counts(str(tmp_path / "nope.db")) == {}


def test_on_admits_lib_top_with_evidence(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, params=ON, **GOOD)
    assert r.admit and r.channel == "match_solo_5b" and r.provenance == "match_solo_5b" and r.char == "百"
    assert r.doubts == []
    assert r.evidence["solo_5b"] == {"lib": "百", "cov": 0.985, "gap": 0.035, "rare": "百", "n_trusted": 40}


@pytest.mark.parametrize("kw", [
    dict(cands=(("古", 0.982), ("舌", 0.945)), rare=["右", "古"]),     # 001:120:9:17：5-b 首位不是库首位
    dict(cands=(("主", 0.983), ("王", 0.978)), rare=["主", "王"]),     # 002:51:5:5：领先第二名不到 0.01
    dict(cands=(("丸", 0.988), ("九", 0.95)), rare=["丸", "九"]),      # 库首位刻例太少（丸 2 例）
    dict(cands=(("百", 0.975), ("白", 0.95)), rare=["百"]),           # cov 不到
    dict(cands=(("百", 0.985), ("白", 0.95)), rare=None),             # 没有 5-b 产物 → 弃权
    dict(cands=(("百", 0.985), ("白", 0.95)), rare=[]),               # 5-b 为空 → 弃权
    dict(cands=(("百", 0.985), ("白", 0.95)), rare=["百"], guard="never_match"),
])
def test_blocked_cases_stay_in_review(tmp_path, monkeypatch, kw):
    r = _run(tmp_path, monkeypatch, params=ON, **kw)
    assert not r.admit and r.channel is None and "solo_5b" not in r.evidence


def test_decide_pure():
    kw = dict(n_lib=KEBEN, doubts=[], guard=None, cov_min=0.98, gap_min=0.01, min_n=3,
              are_variants=lambda a, b: False, group_chars=frozenset("己已巳"), near_form_chars=frozenset("士土"))
    assert solo_5b_decide(cands=[("百", 0.985), ("白", 0.95)], rare_top="百", **kw) == ("百", 0.985, 0.035)
    assert solo_5b_decide(cands=[("百", 0.985), ("白", 0.95)], rare_top="百", **{**kw, "doubts": ["near_form"]}) is None
    assert solo_5b_decide(cands=[("士", 0.99)], rare_top="士", **{**kw, "n_lib": 50}) is None      # 形近表
    assert solo_5b_decide(cands=[("己", 0.99)], rare_top="己", **{**kw, "n_lib": 50}) is None      # 字组／己已巳
    # 第二名是首位的异体：不算对手，领先量看下一名
    av = lambda a, b: {a, b} == {"百", "佰"}  # noqa: E731
    assert solo_5b_decide(cands=[("百", 0.985), ("佰", 0.983), ("白", 0.95)], rare_top="佰",
                          **{**kw, "are_variants": av}) == ("百", 0.985, 0.035)


def test_borrow_db_param_invisible_when_unset():
    assert "solo_5b_borrow_db" not in SeedAdmitParams().model_dump()
    assert "solo_5b_borrow_db" not in SeedAdmitParams(solo_5b_cov=0.98).model_dump()
    assert SeedAdmitParams(solo_5b_cov=0.98, solo_5b_borrow_db="/x/y.db").model_dump()["solo_5b_borrow_db"] == "/x/y.db"


def test_borrowed_flag_marks_stratum(tmp_path, monkeypatch):
    """本书可信刻例 1（<3）、借库后 40：放行并标 borrowed，抽检单独成层。"""
    monkeypatch.setattr(sa, "_trusted_keben_counts",
                        lambda _db, borrow=None: {**KEBEN, "百": 40} if borrow else {**KEBEN, "百": 1})
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[dict(slot=1, verdict="unsure", char=None, cov=0.985, wmax=16.0, guard=None,
                                         candidates=[("百", 0.985), ("白", 0.95)])]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[dict(slot=1, char=None, margin=0.0, source="prior")]))
    write_product(ctx, "rare_candidates", PAGE, rare_candidates=_rare(["百", "白"]))
    ctx.params["seed_admit"] = SeedAdmitParams(patch_missing="skip", solo_5b_cov=0.98, solo_5b_borrow_db="/b.db")
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    (r,) = col.chars
    assert r.admit and r.evidence["solo_5b"]["borrowed"] is True and r.evidence["solo_5b"]["n_trusted"] == 40


# ── 字级白名单（solo_5b_char_ok）──────────────────────────────────────────
def test_char_ok_pure():
    f = sa.solo_5b_char_allowed
    assert f("百", None, {}, 1)                       # 没设名单＝不限
    assert f("百", "百年", {}, 1)                      # 在名单里
    assert f("牟", "百年", {"牟": 1}, 1)               # 不在名单、人裁够
    assert not f("牟", "百年", {"牟": 0}, 1)           # 不在名单、没人裁
    assert not f("牟", "百年", {}, 1)


def test_char_ok_param_invisible_when_unset(tmp_path):
    db = str(tmp_path / "g.db")
    assert not [k for k in SeedAdmitParams(db_path=db, solo_5b_cov=0.98).model_dump() if "char_ok" in k or "human_min" in k]
    on = SeedAdmitParams(db_path=db, solo_5b_cov=0.98, solo_5b_char_ok="百").model_dump()
    assert on["solo_5b_char_ok"] == "百" and on["solo_5b_human_min"] == 1


def test_char_ok_blocks_unlisted_without_human(tmp_path, monkeypatch):
    monkeypatch.setattr(sa, "_human_keben_counts", lambda _db: {})
    r = _run(tmp_path, monkeypatch, params={**ON, "solo_5b_char_ok": "年"}, **GOOD)
    assert not r.admit


def test_char_ok_admits_listed_and_human(tmp_path, monkeypatch):
    monkeypatch.setattr(sa, "_human_keben_counts", lambda _db: {})
    assert _run(tmp_path, monkeypatch, params={**ON, "solo_5b_char_ok": "百"}, **GOOD).admit
    monkeypatch.setattr(sa, "_human_keben_counts", lambda _db: {"百": 2})
    assert _run(tmp_path, monkeypatch, params={**ON, "solo_5b_char_ok": "年"}, **GOOD).admit


def test_same_cov_lowers_threshold_only_for_same_verdict(tmp_path, monkeypatch):
    """库判 same（consensus）、cov 0.968 的格：开 solo_5b_same_cov 0.95 才放；unsure 的照旧不放。"""
    kw = dict(cands=(("百", 0.968), ("白", 0.93)), rare=["百", "白"])
    assert not _run(tmp_path, monkeypatch, params=ON, verdict="same", **kw).admit
    on2 = {**ON, "solo_5b_same_cov": 0.95}
    r = _run(tmp_path, monkeypatch, params=on2, verdict="same", **kw)
    assert r.admit and r.channel == "match_solo_5b" and r.char == "百"
    assert not _run(tmp_path, monkeypatch, params=on2, verdict="unsure", **kw).admit


def test_same_cov_param_invisible_when_unset():
    assert "solo_5b_same_cov" not in SeedAdmitParams(solo_5b_cov=0.98).model_dump()
