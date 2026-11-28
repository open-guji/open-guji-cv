# -*- coding: utf-8 -*-
"""共识升档的 same 退回原档（A23，全唐文 r15 回退 46 格，QTW 看图 11-06）：
Step6 `consensus_as_unsure`、准入 `consensus_fallback`、对位 `coord_consensus_not_same`。自造数据。"""
from __future__ import annotations

import open_guji_cv.feedback.lookup as lookup
import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_align_ref, page_decision, page_match, write_product
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.context_decide import ContextDecideParams
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _consensus_fallback

BOOK, PAGE, COL = "tbook", 1, 1


def _key(slot):
    return f"{BOOK}:{PAGE}:{COL}:{slot}"


def test_params_dump_hidden_when_off():
    assert "consensus_as_unsure" not in ContextDecideParams(corpus_fingerprint="x").model_dump()
    assert "consensus_fallback" not in SeedAdmitParams().model_dump()
    assert SeedAdmitParams(consensus_fallback=True).model_dump()["consensus_fallback"] is True
    assert ContextDecideParams(corpus_fingerprint="x", consensus_as_unsure=True).model_dump()["consensus_as_unsure"]


# ── 准入：_consensus_fallback ─────────────────────────────

def _match():
    return page_match(PAGE, BOOK, col=COL, recs=[
        dict(slot=1, verdict="same", char="簡", cov=0.995, via="consensus:5", candidates=[("簡", 0.995)]),
        dict(slot=2, verdict="same", char="爲", cov=0.995, via="consensus:5", candidates=[("爲", 0.995)]),
        dict(slot=3, verdict="same", char="夭", cov=0.995, via="consensus:5", candidates=[("夭", 0.995)]),
        dict(slot=4, verdict="same", char="山", cov=0.999, matched_id="g1", candidates=[("山", 0.999)]),
    ])


def test_fallback_demotes_consensus_same_unless_ref_agrees():
    m = _match()
    amap = {_key(2): ("爲", "equal"), _key(3): ("天", "replace"), _key(4): ("出", "replace")}
    out = _consensus_fallback(m, amap)
    got = {r.slot: r for r in out.columns[0].chars}
    assert (got[1].verdict, got[1].char, got[1].via) == ("unsure", None, None)     # 整理本缺字
    assert got[2] is m.columns[0].chars[1]                                         # 与整理本同字，照旧 same
    assert (got[3].verdict, got[3].char) == ("unsure", None)                       # 与整理本不同
    assert got[4] is m.columns[0].chars[3]                                         # 不是共识升档的 same 不碰
    assert got[1].candidates == [("簡", 0.995)]


def test_fallback_noop_returns_same_object():
    m = page_match(PAGE, BOOK, col=COL, recs=[dict(slot=1, verdict="same", char="山", cov=0.999)])
    assert _consensus_fallback(m, {}) is m


# ── Step6：consensus_as_unsure ─────────────────────────────

def _ctx_run(tmp_path, monkeypatch, on):
    tmp_path.mkdir(parents=True, exist_ok=True)
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("文華殿大學士臣紀昀等奉敕撰。" * 200, encoding="utf-8")
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    ctx.params["context_decide"] = ContextDecideParams(
        corpus=str(corpus), general_corpus_dir=str(tmp_path / "none"), consensus_as_unsure=on)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, col=COL, recs=[
        dict(slot=1, verdict="same", char="文", cov=0.999, matched_id="g1"),
        dict(slot=2, verdict="same", char="垂", cov=0.995, via="consensus:4",
             candidates=[("垂", 0.995), ("華", 0.96)]),
        dict(slot=3, verdict="unsure", cov=0.96, candidates=[("殿", 0.60), ("展", 0.55)]),
    ]))
    d = STEPS["context_decide"].run_page(ctx, PAGE)["context_decision"]
    return {r.slot: r for cc in d.columns for r in cc.chars}


def test_context_decides_consensus_same_like_unsure(tmp_path, monkeypatch):
    off = _ctx_run(tmp_path / "a", monkeypatch, False)
    assert off[2].source == "db_same" and off[2].char == "垂"
    on = _ctx_run(tmp_path / "b", monkeypatch, True)
    assert on[1].source == "db_same"                       # 真 same 照旧继承
    assert on[2].source != "db_same"                       # 共识 same 交给上下文
    assert on[2].char in (None, "垂", "華")


# ── 准入整步：共识 same 被 same 档防线拦 → 开了退回 context 通道 ─────────────

def _admit(tmp_path, monkeypatch, on, ctx_on):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    monkeypatch.setattr(lookup, "human_chars", lambda *a, **k: {})
    ctx = RunContext(make_book(BOOK), ProductStore(products), ImageCache(cache),
                     params={"seed_admit": SeedAdmitParams(consensus_fallback=on, patch_missing="skip")}, log=lambda s: None)
    chars = ["山", "簡", "水"]
    recs = [dict(slot=i + 1, verdict="same", cov=1.0, wmax=0.0, char=c, candidates=[(c, 1.0)])
            for i, c in enumerate(chars)]
    recs[1] = dict(slot=2, verdict="same", cov=0.97, wmax=3.0, char="簡", via="consensus:5",
                   candidates=[("簡", 0.97), ("蕑", 0.91)])
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(PAGE, BOOK, col=COL, recs=[
        dict(slot=1, char="山", margin=1.0, source="db_same"),
        # Step6 没开 consensus_as_unsure 时共识 same 当 db_same 继承；开了才有上下文裁决
        (dict(slot=2, char="簡", margin=0.95, source="context", ranked=[("簡", 0.95), ("蕑", 0.05)]) if ctx_on
         else dict(slot=2, char="簡", margin=1.0, source="db_same", ranked=[("簡", 1.0)])),
        dict(slot=3, char="水", margin=1.0, source="db_same"),
    ]))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
        PAGE, BOOK, col=COL, recs=[dict(slot=1, align_char="山"), dict(slot=3, align_char="水")]))
    page = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    return {r.slot: r for cc in page.columns for r in cc.chars}


def test_admit_fallback_end_to_end(tmp_path, monkeypatch):
    """整理本缺字的格（全唐文 簡，Kanripo 脱字）：共识升成 same 后 Step6 当 db_same、准入 same 档防线拦；
    两个开关一起开，退回升档前的 context 通道放行，字不变。"""
    off = _admit(tmp_path / "a", monkeypatch, False, False)
    assert not off[2].admit and any("库 same 但准入被拦" in x for x in off[2].doubts)
    on = _admit(tmp_path / "b", monkeypatch, True, True)
    assert on[2].admit and on[2].char == "簡" and on[2].channel == "context"
    assert on[1].admit and on[3].admit and (on[1].channel, on[3].channel) == (off[1].channel, off[3].channel)
    half = _admit(tmp_path / "c", monkeypatch, True, False)          # 只开准入：没有上下文裁决，照旧留审
    assert not half[2].admit


# ── align_ref：coord_consensus_not_same ─────────────────────────────

def test_align_ref_flag_hidden_when_off():
    from open_guji_cv.steps.align_ref import AlignRefParams
    assert "coord_consensus_not_same" not in AlignRefParams().model_dump()
    assert AlignRefParams(coord_consensus_not_same=True).model_dump()["coord_consensus_not_same"] is True


def test_coord_conflict_ignores_consensus_same_on_blank():
    """史記 r18 09:183：空格位上的「○」被共识升成 same，坐标冲突闸整列退回。共识 same 不算库 same 时不退。"""
    from open_guji_cv.steps.align_ref import _coord_conflict
    recs = [(_key(1), 1, "", "山", 0.0), (_key(2), 2, "", "", 1.0), (_key(3), 3, "", "水", 2.0)]
    assert _coord_conflict(recs, {}, {_key(2): "○"}).startswith("空格位上库认出了字")
    assert not _coord_conflict(recs, {}, {})
