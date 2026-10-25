# -*- coding: utf-8 -*-
"""铁证放行遇对照刻例原图缺失 → 转待审（`seed_admit.iron_ex_missing_guard`，overview#554）：只收紧。自造数据。"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
import open_guji_cv.steps.seed_admit as sa
from helpers import make_book, page_align_ref, page_match, write_product
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1


def _run(tmp_path, monkeypatch, params, n_missing):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    ctx = RunContext(make_book(BOOK, iron_gate=True), ProductStore(products), ImageCache(cache),
                     params={"seed_admit": params.model_copy(update={"shadow_veto": False})},   # 影子闸要真字形库，这里没摆
                     log=lambda s: None)
    recs = [dict(slot=1, verdict="unsure", cov=0.5, wmax=0.0, char="山", candidates=[("山", 0.5)])]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
        PAGE, BOOK, recs=[dict(slot=1, align_char="水")], col=COL))

    def fake_decide(book, page, col, r, iron_ctx, scale, ns, missing=None):
        if missing is not None:
            missing.extend(f"vol02:1:1:{i}" for i in range(n_missing))
        return "山"

    monkeypatch.setattr(sa, "_iron_context", lambda *a, **k: object())
    monkeypatch.setattr(sa, "_iron_page_scale", lambda *a, **k: 1.0)
    monkeypatch.setattr(sa, "_iron_decide", fake_decide)
    monkeypatch.setattr(sa, "_iron_confusable_witness", lambda *a, **k: False)
    import open_guji_cv.clustering.seeding as seeding
    monkeypatch.setattr(seeding, "context_conflicts_ref", lambda *a, **k: False)
    page = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    return {r.slot: r for cc in page.columns for r in cc.chars}


def test_default_on():
    assert SeedAdmitParams().iron_ex_missing_guard is True


def test_missing_exemplar_demotes(tmp_path, monkeypatch):
    got = _run(tmp_path, monkeypatch, SeedAdmitParams(), n_missing=2)
    r = got[1]
    assert not r.admit and "iron_ex_missing" in r.doubts and r.channel != "iron"
    assert r.evidence["iron_ex_missing"] == 2


def test_nothing_missing_same_as_guard_off(tmp_path, monkeypatch):
    on = _run(tmp_path, monkeypatch, SeedAdmitParams(), n_missing=0)
    off = _run(tmp_path / "b", monkeypatch, SeedAdmitParams(iron_ex_missing_guard=False), n_missing=0)
    assert on[1].admit and on[1].channel == "iron" and on[1].char == "山"
    assert (on[1].admit, on[1].channel, on[1].char, on[1].doubts) == \
           (off[1].admit, off[1].channel, off[1].char, off[1].doubts)
    assert "iron_ex_missing" not in on[1].evidence


def test_guard_off_keeps_old_behaviour(tmp_path, monkeypatch):
    got = _run(tmp_path, monkeypatch, SeedAdmitParams(iron_ex_missing_guard=False), n_missing=3)
    assert got[1].admit and got[1].channel == "iron"


def test_real_iron_decide_collects_only_cache_misses(tmp_path, monkeypatch):
    """真走 `_iron_decide` 里的 `raw_of`：有图／缓存无图／`v1:` 旧坐标各一例，
    `missing` 只含缓存无图那一例（`v1:` 属「本来就认不出」，不算缺）。"""
    import numpy as np
    import open_guji_cv.clustering.iron_evidence as ie
    import open_guji_cv.clustering.normalize as nm

    cache_root = tmp_path / "cache"
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache_root))
    ImageCache(cache_root).put("vol02", "char_patch", "p0005c03s7", np.full((20, 20), 200, np.uint8))

    class _Match:
        verdict, char, cov = "unsure", None, 0.5
        candidates = [("山", 0.5)]

    class _Matcher:
        def match(self, *a, **k):
            return _Match()

    monkeypatch.setattr(sa, "_page_patch", lambda *a, **k: np.zeros((20, 20), np.uint8))
    monkeypatch.setattr(nm, "normalize_patch", lambda img, **k: img)
    seen = {}

    def fake_iron_with_disc(cands, human_chars_set, partners_map, img, ex_raws, scale):
        seen["n_raw"] = len(ex_raws("山"))
        return "山", None, None, None, None

    monkeypatch.setattr(ie, "iron_with_disc", fake_iron_with_disc)
    ids = ["vol02:5:3:7", "vol02:6:4:8", "v1:5:3:7"]
    r = type("R", (), dict(id="tbook:1:1:1", slot=1, sub=None))()
    ctx = (_Matcher(), {"山"}, {}, {"山": ids})
    missing: list = []
    assert sa._iron_decide(object(), 1, 1, r, ctx, 1.0, None, missing) == "山"
    assert missing == ["vol02:6:4:8"] and seen["n_raw"] == 1
    # 不传 missing（护栏关）：行为不变
    assert sa._iron_decide(object(), 1, 1, r, ctx, 1.0, None) == "山"
