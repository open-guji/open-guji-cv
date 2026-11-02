# -*- coding: utf-8 -*-
"""人裁绑丢闸（`seed_admit.human_unbound_review`，GUJI-697）：绑定后不采信的人裁不许被新放行悄悄顶掉。自造数据。"""
from __future__ import annotations

import open_guji_cv.feedback.lookup as lookup
import open_guji_cv.steps  # noqa: F401
from helpers import make_book, page_align_ref, page_match, write_product
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.feedback.events import Event, EventLog, EventTarget as Target
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1
CHARS = ["山", "水", "木"]


def _run(tmp_path, monkeypatch, params, lost):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    real = lookup.human_chars

    def fake(book, log=None, stale=None, bind=None, lost=None):
        if lost is not None:
            lost.update(LOST)
        return {}
    LOST = lost
    monkeypatch.setattr(lookup, "human_chars", fake)
    ctx = RunContext(make_book(BOOK), ProductStore(products), ImageCache(cache),
                     params={"seed_admit": params}, log=lambda s: None)
    recs = [dict(slot=i + 1, verdict="same", cov=1.0, wmax=0.0, char=c, candidates=[(c, 1.0)])
            for i, c in enumerate(CHARS)]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
        PAGE, BOOK, recs=[dict(slot=i + 1, align_char=c) for i, c in enumerate(CHARS)], col=COL))
    page = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    monkeypatch.setattr(lookup, "human_chars", real)
    return {r.slot: r for cc in page.columns for r in cc.chars}, page


def _key(slot):
    return f"{BOOK}:{PAGE}:{COL}:{slot}"


def test_default_on():
    assert SeedAdmitParams().human_unbound_review is True


def test_no_lost_changes_nothing(tmp_path, monkeypatch):
    r, _ = _run(tmp_path, monkeypatch, SeedAdmitParams(), {})
    assert all(x.admit for x in r.values())
    assert not any("human_unbound" in (x.evidence or {}) for x in r.values())


def test_lost_ruling_differs_demotes(tmp_path, monkeypatch):
    lost = {_key(2): {"char": "火", "status": "review", "event": "e1"}}
    r, page = _run(tmp_path, monkeypatch, SeedAdmitParams(), lost)
    x = r[2]
    assert not x.admit and x.channel is None and "human_unbound" in x.doubts
    assert x.char == "水"                       # 只降级、不改字
    assert x.evidence["human_unbound"]["char"] == "火"
    assert x.evidence["demoted_from"]["by"] == "human_unbound"
    assert r[1].admit and r[3].admit
    assert page.n_review >= 1


def test_lost_ruling_agrees_keeps_admit(tmp_path, monkeypatch):
    lost = {_key(2): {"char": "水", "status": "void", "event": "e1"}}
    r, _ = _run(tmp_path, monkeypatch, SeedAdmitParams(), lost)
    assert r[2].admit and r[2].evidence["human_unbound"]["char"] == "水"


def test_switch_off_ignores_lost(tmp_path, monkeypatch):
    lost = {_key(2): {"char": "火", "status": "review", "event": "e1"}}
    r, _ = _run(tmp_path, monkeypatch, SeedAdmitParams(human_unbound_review=False), lost)
    assert r[2].admit and "human_unbound" not in (r[2].evidence or {})


def test_shift_ok_off_by_default_demotes(tmp_path, monkeypatch):
    # 旧人裁「山」＝整理本上一格的字，像是旧编号顺移；开关缺省关 → 照旧降级
    lost = {_key(2): {"char": "山", "status": "unanchored", "event": "e1"}}
    r, _ = _run(tmp_path, monkeypatch, SeedAdmitParams(), lost)
    assert not r[2].admit and "human_unbound" in r[2].doubts


def test_shift_ok_keeps_admit_when_ruling_matches_neighbour(tmp_path, monkeypatch):
    lost = {_key(2): {"char": "山", "status": "unanchored", "event": "e1"}}
    r, _ = _run(tmp_path, monkeypatch, SeedAdmitParams(human_unbound_shift_ok=True), lost)
    assert r[2].admit and r[2].char == "水"
    assert r[2].evidence["human_unbound"]["shift_ok"] == -1


def test_shift_ok_needs_unanchored_and_neighbour(tmp_path, monkeypatch):
    p = SeedAdmitParams(human_unbound_shift_ok=True)
    # 有几何却对不上（review）→ 不豁免
    r, _ = _run(tmp_path, monkeypatch, p, {_key(2): {"char": "山", "status": "review", "event": "e1"}})
    assert not r[2].admit
    # 旧字在 ±2 格整理本里都没有 → 不豁免
    r, _ = _run(tmp_path, monkeypatch, p, {_key(2): {"char": "火", "status": "unanchored", "event": "e1"}})
    assert not r[2].admit


def test_shift_ok_not_in_params_dump():
    assert "human_unbound_shift_ok" not in SeedAdmitParams().model_dump()
    assert SeedAdmitParams(human_unbound_shift_ok=True).model_dump()["human_unbound_shift_ok"] is True


def test_human_chars_reports_lost(tmp_path, monkeypatch):
    """`human_chars(lost=…)`：绑定不可用的裁决按原编号记下；同一格之后又有可用裁决的不记。"""
    import open_guji_cv.feedback.bindings as bindings
    log = EventLog(tmp_path / "events")
    def ev(i, slot, ch, ts):
        return Event(id=f"e{i}", batch="b", seq=i, ts=ts, kind="confirm",
                     target=Target(step="seed_admit", unit="cell", key=_key(slot)), payload={"v": "confirm", "shape": ch})
    evs = [ev(1, 1, "火", "2026-10-01T00:00:00Z"), ev(2, 2, "土", "2026-10-01T00:00:00Z"),
           ev(3, 2, "金", "2026-10-02T00:00:00Z")]
    rows = {"e1": {"status": "review", "bound": None}, "e2": {"status": "void", "bound": None},
            "e3": {"status": "valid", "bound": _key(2)}}
    import open_guji_cv.feedback.events as events
    monkeypatch.setattr(events, "iter_events_readonly", lambda _log: evs)
    monkeypatch.setattr(events, "counts_as_human", lambda e: True)
    monkeypatch.setattr(bindings, "book_bindings", lambda book, log=None: rows)
    lost: dict = {}
    out = lookup.human_chars(BOOK, log=log, stale={}, bind=True, lost=lost)
    assert out == {_key(2): "金"}
    assert set(lost) == {_key(1)} and lost[_key(1)]["char"] == "火" and lost[_key(1)]["status"] == "review"


import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")   # 老测试按「放行开关缺省全关」造的数据，见 conftest
