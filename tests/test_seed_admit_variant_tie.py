# -*- coding: utf-8 -*-
"""Step7 异体并列放行（`variant_tie`，Y1 / overview#471）：top1 与近邻是同一个字的两个码位而并列 → 放行 top1；缺省关。"""
from __future__ import annotations

import pytest

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_decision, page_match, write_product
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1


@pytest.fixture(autouse=True)
def _isolate_variant_graph(monkeypatch):
    """`_direct_variant_edge` 会懒加载 `open_guji_cv.variants` 的全局图单例；测完把它还原，不污染别的测试。"""
    import open_guji_cv.variants as vm
    monkeypatch.setattr(vm, "_GRAPH", vm._GRAPH)


def _run(tmp_path, monkeypatch, cands, params=None, guard=None):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, col=COL, recs=[
        dict(slot=1, verdict="unsure", cov=cands[0][1], wmax=10.0, candidates=list(cands), guard=guard)]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[dict(slot=1, char=None, margin=0.1, source="prior")]))
    # 灰区无整理本时会走 CNN 背书去读字块；测试不造 cells，字块读不到就跳过这一路（不依赖本机缓存）
    ctx.params["seed_admit"] = SeedAdmitParams(**{"patch_missing": "skip", **(params or {})})
    return STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns[0].chars[0]


ON = {"variant_tie": True}


def test_default_off(tmp_path, monkeypatch):
    assert not _run(tmp_path, monkeypatch, [("𢑴", 0.975), ("彝", 0.972)]).admit
    assert "variant_tie" not in SeedAdmitParams().model_dump()


def test_variant_pair_released_with_top1(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, [("𢑴", 0.975), ("彝", 0.972)], ON)
    assert r.admit and r.channel == "variant_tie" and r.char == "𢑴"


def test_extra_group(tmp_path, monkeypatch):
    c = [("𫎇", 0.98), ("蒙", 0.975)]
    assert not _run(tmp_path, monkeypatch, c, ON).admit
    assert _run(tmp_path, monkeypatch, c, {**ON, "variant_tie_extra": "𫎇蒙"}).char == "𫎇"


def test_non_variant_neighbour_blocks(tmp_path, monkeypatch):
    assert not _run(tmp_path, monkeypatch, [("𢑴", 0.975), ("彝", 0.972), ("家", 0.971)], ON).admit


def test_low_cov_and_guard_block(tmp_path, monkeypatch):
    assert not _run(tmp_path, monkeypatch, [("𢑴", 0.95), ("彝", 0.94)], ON).admit
    assert not _run(tmp_path, monkeypatch, [("𢑴", 0.975), ("彝", 0.972)], ON, guard="never_match").admit


def test_confusable_top1_blocked(tmp_path, monkeypatch):
    assert not _run(tmp_path, monkeypatch, [("土", 0.98), ("士", 0.975)], ON).admit


def test_extra_table_replaces_variants_json_edges(tmp_path, monkeypatch):
    """给了组表就只认组表：𢑴／彝 在 variants.json 里有边，但组表里没有它们 → 不放。"""
    c = [("𢑴", 0.975), ("彝", 0.972)]
    assert _run(tmp_path, monkeypatch, c, ON).admit
    assert not _run(tmp_path, monkeypatch, c, {**ON, "variant_tie_extra": "𫎇蒙"}).admit


# ── variant_tie_margin：组表字 cov 门槛降到 0.96（Y1，overview#471）──────────────

TAB = {"variant_tie_extra": "𫎇蒙"}
WIDE = {**ON, **TAB, "variant_tie_margin": True}


def test_margin_off_by_default_and_not_in_dump():
    d = SeedAdmitParams(variant_tie=True).model_dump()
    assert "variant_tie_margin" not in d and "variant_tie_margin_cov" not in d
    d = SeedAdmitParams(variant_tie=True, variant_tie_margin=True).model_dump()
    assert d["variant_tie_margin"] is True and d["variant_tie_margin_cov"] == 0.96


def test_margin_lowers_cov_gate_for_table_group(tmp_path, monkeypatch):
    c = [("𫎇", 0.965), ("蒙", 0.96)]
    assert not _run(tmp_path, monkeypatch, c, {**ON, **TAB}).admit          # 0.965 < 0.97
    r = _run(tmp_path, monkeypatch, c, WIDE)
    assert r.admit and r.channel == "variant_tie" and r.char == "𫎇"


def test_margin_keeps_floor_neighbour_and_table_rules(tmp_path, monkeypatch):
    assert not _run(tmp_path, monkeypatch, [("𫎇", 0.955), ("蒙", 0.95)], WIDE).admit          # 低于 0.96 照拦
    assert not _run(tmp_path, monkeypatch, [("𫎇", 0.975), ("蒙", 0.97), ("家", 0.955)], WIDE).admit   # 近邻 gap<0.03 不在组内
    assert not _run(tmp_path, monkeypatch, [("𫎇", 0.965), ("蒙", 0.96)], WIDE, guard="never_match").admit
    # 没给组表时不放宽（只有给了组表才有「组表字」可言）
    assert not _run(tmp_path, monkeypatch, [("𢑴", 0.965), ("彝", 0.96)], {**ON, "variant_tie_margin": True}).admit
