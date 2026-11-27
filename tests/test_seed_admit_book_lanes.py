# -*- coding: utf-8 -*-
"""seed_admit 书级放行通道钩子 `impl/keben/admit_lanes.noref_lanes` 与参数 `book_lanes`（2026-11-24 CV4）。数据自造。"""
from types import SimpleNamespace as NS

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.impl.keben import admit_lanes
from open_guji_cv.steps import seed_admit as sa
from open_guji_cv.steps.seed_admit import SeedAdmitParams
from open_guji_cv.steps.seed_admit_params import _MOVED_TO_BOOK


def test_default_hook_is_none_and_not_in_dump():
    assert admit_lanes.noref_lanes is None
    d = SeedAdmitParams(db_path="x").model_dump()
    assert "book_lanes" not in d and "book_lanes_fingerprint" not in d
    d = SeedAdmitParams(db_path="x", book_lanes={"solo_cal": {"tiers": "0.98:0.03"}}).model_dump()
    assert d["book_lanes"] == {"solo_cal": {"tiers": "0.98:0.03"}}


def test_moved_keys_default_ignored_other_values_refused():
    base = SeedAdmitParams(db_path="x").model_dump()
    assert SeedAdmitParams(db_path="x", **_MOVED_TO_BOOK).model_dump() == base
    for k, v in (("solo_cal", True), ("num_run_cov", 0.995), ("solo_adapt_pct", "p10"), ("lead_5b", True)):
        with pytest.raises(ValueError, match="book_lanes"):
            SeedAdmitParams(db_path="x", **{k: v})


def test_data_fingerprint(tmp_path, monkeypatch):
    f = tmp_path / "prof.json"
    f.write_text("{}", encoding="utf-8")
    p1 = SeedAdmitParams(db_path="x", book_lanes={"data": [str(f)]})
    f.write_text('{"a": 1}', encoding="utf-8")
    p2 = SeedAdmitParams(db_path="x", book_lanes={"data": [str(f)]})
    assert p1.book_lanes_fingerprint and p1.book_lanes_fingerprint != p2.book_lanes_fingerprint
    p3 = SeedAdmitParams(db_path="x", book_lanes={"data": [str(tmp_path / "missing.json")]})
    assert p3.book_lanes_fingerprint.endswith(":missing")
    with pytest.raises(ValueError, match="路径表"):
        SeedAdmitParams(db_path="x", book_lanes={"data": "x.json"})


def test_hook_missing_refuses(monkeypatch):
    monkeypatch.setattr("open_guji_cv.core.seg_set.resolve", lambda book, mod: mod)
    with pytest.raises(RuntimeError, match="admit_lanes"):
        sa._admit_lanes_hook(NS(book=None))


def test_hook_resolved_and_facts(monkeypatch):
    called = {}

    def fake(**kw):
        called.update(kw)
        return 0
    monkeypatch.setattr(admit_lanes, "noref_lanes", fake)
    monkeypatch.setattr("open_guji_cv.core.seg_set.resolve", lambda book, mod: mod)
    hook = sa._admit_lanes_hook(NS(book=None))
    facts = sa._AdmitFacts(NS(book=NS(codepoints={}, canonical_char=None)))
    assert hook(out=[], mmap={}, amap={}, rare=None, coord={}, params={"x": 1}, facts=facts) == 0
    assert called["params"] == {"x": 1}
    assert facts.canonical_char is None and facts.is_gap("〓") in (True, False)
    assert facts.are_variants("羨", "羡") and facts.is_hanzi("甲") and not facts.is_hanzi("a")
    assert facts.data_path("/no/such/file.json") == ""
