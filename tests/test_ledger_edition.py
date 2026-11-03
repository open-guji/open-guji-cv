# -*- coding: utf-8 -*-
"""用字账按书选（2026-11-03）：殿本与认不出书的册照旧读殿本账、参数逐字节不变；别的书读自己的（没有就空账）。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from open_guji_cv.core import ledger_edition as LE
from open_guji_cv.core.step import _with_book_ledger
from open_guji_cv.steps.seed_admit import SeedAdmitParams


@pytest.mark.parametrize("key,want", [(None, "wuyingdian_zongmu"), ("96mid1ogzk", "wuyingdian_zongmu"),
                                      (sorted(LE.ZONGMU_KEYS)[1], "wuyingdian_zongmu"), ("988g3f0wsu", "988g3f0wsu")])
def test_edition_for(monkeypatch, key, want):
    monkeypatch.setattr(LE, "book_key", lambda vol: key)
    assert LE.edition_for("vol01") == want


def _ctx():
    return SimpleNamespace(book=SimpleNamespace(id="01"))


def test_zongmu_params_unchanged(monkeypatch):
    monkeypatch.setattr(LE, "book_key", lambda vol: "96mid1ogzk")
    p = SeedAdmitParams()
    assert _with_book_ledger(p, _ctx()) is p


def test_other_book_switches_to_own_ledger(monkeypatch):
    monkeypatch.setattr(LE, "book_key", lambda vol: "988g3f0wsu")
    p = SeedAdmitParams()
    q = _with_book_ledger(p, _ctx())
    assert q.edition == "988g3f0wsu"
    assert q.ledger_fingerprint and q.ledger_fingerprint != p.ledger_fingerprint   # 按新键（没有的文件）重算


def test_explicit_edition_kept(monkeypatch):
    monkeypatch.setattr(LE, "book_key", lambda vol: "988g3f0wsu")
    p = SeedAdmitParams(edition="other")
    assert _with_book_ledger(p, _ctx()) is p


def test_book_key_from_book_id(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    (ws / "books").mkdir(parents=True)
    (ws / "config").mkdir()
    (ws / "config" / "book_defaults.yaml").write_text("book_id: 988g3f0wsu\n", encoding="utf-8")
    (ws / "books" / "01.yaml").write_text("id: '01'\n", encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    assert LE.book_key("01") == "988g3f0wsu"
    assert LE.edition_for("01") == "988g3f0wsu"
