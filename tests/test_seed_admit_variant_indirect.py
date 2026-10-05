# -*- coding: utf-8 -*-
"""异体等价放行拦间接路径（`variant_indirect_guard`，2026-09-28，overview#178）。

两例真实格钉住：
- `𢑴`/`彞`：关系层里两者**没有直接边**，是 `𢑴→彝`（hydzd）与 `彞→彝`（twedu）经
  共同正字「彝」间接连起来的。H #62 `vol04:28:3:18a`（`ref_lib`，margin 0.0036，刻
  「彝」形存成 `𢑴`）与 `vol02:151:6:20`（`match_replace`，库 top1 `𢑴` cov 0.9549）
  都是这一对。
- `冶`/`治`：twedu **单向直接边**（bxgb:52:11:15）。本闸只管间接路径，直接边行为不变：
  `ref_lib` 照旧被 `ref_lib_variant_guard` 拦，`match_replace` 照旧放。
  （2026-09-28 overview#201：冶/治 登记进 `never_group.json`，语义层不再同义——
  「单向直接边不变」改用 `𠮓`/`變` 钉，冶/治 与 沙/砂 另起一条钉「不再靠异体等价放行」。）
"""
from __future__ import annotations

import numpy as np

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_decision, page_match, write_product
from open_guji_cv.clustering.variants import VariantMap
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.kinds.recog import AlignRec, PageAlignRef
from open_guji_cv.steps.seed_admit import (SeedAdmitParams, _direct_variant_edge,
                                           _variant_indirect)
from open_guji_cv.variant_ledger import BookLedger

BOOK, PAGE, COL, SLOT = "tbook", 1, 1, 18


def _run(tmp_path, monkeypatch, *, candidates, align_char, margin=None,
         align_op="replace", params=None):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    # 组内定形（`_image_ranks`）要看本格字块；读不到会整页报错（overview#407），
    # 所以摆一张空白字块——本文件测的是关系层，不是图像检索的结果。
    ctx.cache.put(BOOK, "char_patch", f"p{PAGE:04d}c{COL:02d}s{SLOT}",
                  np.full((40, 40), 255, np.uint8))
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[
            dict(slot=SLOT, verdict="unsure", cov=candidates[0][1], wmax=45.31,
                 candidates=candidates)]))
    write_product(ctx, "align_ref", PAGE, align_ref=PageAlignRef(
        page=PAGE, anchored=True,
        chars=[AlignRec(id=f"{BOOK}:{PAGE}:{COL}:{SLOT}", col=COL, slot=SLOT,
                        align_char=align_char, align_op=align_op)]))
    if margin is not None:
        # source 不是 "context"：不走 context 通道，只给 ref_lib 的 margin 分支用。
        write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
            PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, char="丙", margin=margin,
                                            source="prior")]))
    ctx.params["seed_admit"] = SeedAdmitParams(**(params or {}))
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    (r,) = col.chars
    return r


# ref_lib：候选没有断档（不让 match_margin 抢先），cov 照录 vol04:28:3:18a
_REF_LIB = [("𢑴", 0.9314), ("弊", 0.93)]
# match_replace：cov 过 MATCH_REPLACE_COV 0.95，照录 vol02:151:6:20
_REPLACE = [("𢑴", 0.9549), ("弊", 0.95)]


# ── 前提：关系层实况（生产配置，不伪造） ─────────────────────────

def test_relation_layer_facts():
    vm = VariantMap.load(None)
    assert vm.semantic("𢑴") == vm.semantic("彞") == vm.semantic("彝")
    assert _direct_variant_edge("𢑴", "彝") and _direct_variant_edge("彞", "彝")
    assert not _direct_variant_edge("𢑴", "彞"), "有了直接边，本测试的前提就变了"
    assert _direct_variant_edge("冶", "治")   # twedu 单向，但是直接边
    assert _direct_variant_edge("彝", "彞")


def test_guard_default_on():
    assert SeedAdmitParams().variant_indirect_guard is True


# ── 𢑴/彞：间接路径被拦 ──────────────────────────────────────────

def test_ref_lib_indirect_blocked(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, candidates=_REF_LIB, align_char="彞", margin=0.0036)
    assert r.admit is False and r.channel is None
    assert "variant_indirect" in r.doubts and "ref_lib_variant" in r.doubts


def test_ref_lib_indirect_margin_no_longer_passes(tmp_path, monkeypatch):
    """间接路径即便 Step6 margin 过线也不放（直接边的 margin 分支见下一条，不变）。"""
    r = _run(tmp_path, monkeypatch, candidates=_REF_LIB, align_char="彞", margin=0.80)
    assert r.admit is False and "variant_indirect" in r.doubts
    old = _run(tmp_path / "old", monkeypatch, candidates=_REF_LIB, align_char="彞",
               margin=0.80, params={"variant_indirect_guard": False})
    assert old.admit is True and old.channel == "ref_lib" and old.char == "𢑴"


def test_match_replace_indirect_blocked(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, candidates=_REPLACE, align_char="彞")
    assert r.admit is False and "variant_indirect" in r.doubts, (r.channel, r.doubts)
    old = _run(tmp_path / "old", monkeypatch, candidates=_REPLACE, align_char="彞",
               params={"variant_indirect_guard": False})
    assert old.admit is True and old.channel == "match_replace" and old.char == "彞"


def test_match_margin_indirect_blocked(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, candidates=[("𢑴", 0.93), ("弊", 0.80)],
             align_char="彞")
    assert r.admit is False and "variant_indirect" in r.doubts, (r.channel, r.doubts)
    old = _run(tmp_path / "old", monkeypatch, candidates=[("𢑴", 0.93), ("弊", 0.80)],
               align_char="彞", params={"variant_indirect_guard": False})
    assert old.admit is True and old.channel == "match_margin"


def test_trusted_indirect_pair_still_admitted(tmp_path, monkeypatch):
    """人裁/人工表/书级 codepoints 认过的间接对照放（与 `_trusted_variant_edge` 同口径）。"""
    ledger = BookLedger({"groups": {"彝": {"members": ["𢑴", "彞"],
                                          "pairs": {"𢑴→彞": {"human": 1}}}}})
    assert _variant_indirect("𢑴", "彞", ledger, make_book(BOOK)) is False
    assert _variant_indirect("𢑴", "彞", BookLedger({"groups": {}}),
                             make_book(BOOK, codepoints={"𢑴": "彞"})) is False
    assert _variant_indirect("𢑴", "彞", BookLedger({"groups": {}}), make_book(BOOK)) is True


# ── 直接边行为不变 ───────────────────────────────────────────────

def test_direct_bidirectional_unchanged(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, candidates=[("彝", 0.9314), ("弊", 0.93)],
             align_char="彞", margin=0.0036)
    assert r.admit is True and r.channel == "ref_lib" and r.char == "彝"
    assert "variant_indirect" not in r.doubts
    r = _run(tmp_path / "b", monkeypatch, candidates=[("彝", 0.9549), ("弊", 0.95)],
             align_char="彞")
    assert r.admit is True and r.channel == "match_replace"


def test_one_way_direct_edge_unchanged(tmp_path, monkeypatch):
    """𠮓→變（单向直接边，D #178 单向桶里的新旧字形）：ref_lib 照旧由 ref_lib_variant_guard
    拦（不记 variant_indirect），margin 过线照旧放；match_replace 照旧放。"""
    assert _direct_variant_edge("𠮓", "變")
    r = _run(tmp_path, monkeypatch, candidates=[("變", 0.9443), ("泊", 0.939)],
             align_char="𠮓", margin=0.024)
    assert r.admit is False and "ref_lib_variant" in r.doubts
    assert "variant_indirect" not in r.doubts
    r = _run(tmp_path / "m", monkeypatch, candidates=[("變", 0.9443), ("泊", 0.939)],
             align_char="𠮓", margin=0.80)
    assert r.admit is True and r.channel == "ref_lib" and r.char == "變"
    r = _run(tmp_path / "r", monkeypatch, candidates=[("變", 0.9549), ("泊", 0.95)],
             align_char="𠮓")
    assert r.admit is True and r.channel == "match_replace"


def test_never_group_pairs_no_longer_admitted_as_variants(tmp_path, monkeypatch):
    """冶/治、沙/砂（overview#201 登记进 never_group）：语义层不再同义，库形与整理本字不同
    就不能靠异体等价放行——D #178 的真错格 qtw v010:73:2:21（刻「沙」、整理本「砂」、
    match_replace 按「砂」放行）就是这条路。"""
    vm = VariantMap.load(None)
    assert vm.semantic("冶") != vm.semantic("治")
    assert vm.semantic("砂") != vm.semantic("沙")
    for i, (lib, ref) in enumerate([("治", "冶"), ("沙", "砂")]):
        r = _run(tmp_path / f"r{i}", monkeypatch, candidates=[(lib, 0.9549), ("泊", 0.95)],
                 align_char=ref)
        assert r.admit is False, (lib, ref, r.channel)
        r = _run(tmp_path / f"m{i}", monkeypatch, candidates=[(lib, 0.9443), ("泊", 0.939)],
                 align_char=ref, margin=0.80)
        assert not (r.admit and r.channel == "ref_lib"), (lib, ref, r.char)
