# -*- coding: utf-8 -*-
"""撤库重审闸（`seed_admit.evict_review`，Sheldon 2026-11-09）：审阅页上「撤库」的格文本撤下、重新人审。自造数据。"""
from __future__ import annotations

import open_guji_cv.feedback.lookup as lookup
import open_guji_cv.steps  # noqa: F401
from helpers import make_book, page_align_ref, page_match, write_product
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1
CHARS = ["山", "水", "木"]


import pytest

pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")


def _key(slot):
    return f"{BOOK}:{PAGE}:{COL}:{slot}"


def _ev(seq, payload, key="v2:tbook:1:1:2", ts="2026-11-09T00:00:00Z"):
    return make_event("b", seq, "glyph_audit", EventTarget(step="glyph_audit", unit="cell", key=key, book="q"),
                      payload, ts=ts)


def test_lookup_only_review_flagged(tmp_path):
    log = EventLog(tmp_path)
    log.append([_ev(1, {"v": "evict", "instance_id": "v2:tbook:1:1:2", "review": True, "char_self": "水"}),
                _ev(2, {"v": "evict", "instance_id": "v2:tbook:1:1:3"}, key="v2:tbook:1:1:3"),
                _ev(3, {"v": "relabel", "instance_id": "v2:tbook:1:1:1", "char": "火", "review": True}, key="v2:tbook:1:1:1"),
                _ev(4, {"v": "evict", "instance_id": "v2:other:1:1:1", "review": True}, key="v2:other:1:1:1")])
    got = lookup.evict_review_cells(BOOK, log)
    assert set(got) == {_key(2)} and got[_key(2)]["char"] == "水"


def _run(tmp_path, monkeypatch, params, cells):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    monkeypatch.setattr(lookup, "evict_review_cells", lambda book, log=None: dict(cells))
    monkeypatch.setattr(lookup, "human_chars", lambda book, log=None, stale=None, bind=None, lost=None: {})
    ctx = RunContext(make_book(BOOK), ProductStore(products), ImageCache(cache),
                     params={"seed_admit": params}, log=lambda s: None)
    recs = [dict(slot=i + 1, verdict="same", cov=1.0, wmax=0.0, char=c, candidates=[(c, 1.0)])
            for i, c in enumerate(CHARS)]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
        PAGE, BOOK, recs=[dict(slot=i + 1, align_char=c) for i, c in enumerate(CHARS)], col=COL))
    page = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    return {r.slot: r for cc in page.columns for r in cc.chars}, page


def test_default_on():
    assert SeedAdmitParams().evict_review is True


def test_no_events_changes_nothing(tmp_path, monkeypatch):
    r, _ = _run(tmp_path, monkeypatch, SeedAdmitParams(), {})
    assert all(x.admit for x in r.values())
    assert not any("evict_review" in (x.evidence or {}) for x in r.values())


def test_evicted_cell_demoted(tmp_path, monkeypatch):
    r, page = _run(tmp_path, monkeypatch, SeedAdmitParams(), {_key(2): {"char": "水", "event": "e1"}})
    x = r[2]
    assert not x.admit and x.channel is None and "evict_review" in x.doubts
    assert x.evidence["seg_kind"] == "evict_review" and x.evidence["demoted_from"]["by"] == "evict_review"
    assert r[1].admit and r[3].admit and page.n_review >= 1


def test_switch_off(tmp_path, monkeypatch):
    r, _ = _run(tmp_path, monkeypatch, SeedAdmitParams(evict_review=False), {_key(2): {"char": "水", "event": "e1"}})
    assert all(x.admit for x in r.values())
