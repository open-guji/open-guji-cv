# -*- coding: utf-8 -*-
"""推库前拦下：册配置的 corpus 总号在那册钉子账里查不到（多见于写在基础配置里，2026-11-03）。"""
from __future__ import annotations

import json

import pytest

from open_guji_cv.core import corpus_pin as CP


def _ws(tmp_path, defaults: str, books: dict[str, str], pins: dict[str, list[int]]):
    ws = tmp_path / "ws"
    (ws / "books").mkdir(parents=True)
    (ws / "config").mkdir()
    (ws / "config" / "book_defaults.yaml").write_text(defaults, encoding="utf-8")
    for vol, body in books.items():
        (ws / "books" / f"{vol}.yaml").write_text(body, encoding="utf-8")
    for vol, ns in pins.items():
        p = CP.pins_path(ws, vol)
        p.parent.mkdir(parents=True, exist_ok=True)
        rows = [{"n": n, "global": None, "book": 1, "vol": None} for n in ns]
        p.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    return ws


def test_defaults_corpus_missing_in_one_ledger(tmp_path):
    ws = _ws(tmp_path, "corpus: 25\n", {"vol01": "id: vol01\n", "vol02": "id: vol02\n", "vol03": "id: vol03\ncorpus: 24\n"},
             {"vol01": [24, 25], "vol02": [23, 24], "vol03": [24]})
    out = CP.unresolved_pins(ws)
    assert len(out) == 1 and "vol02" in out[0] and "基础配置" in out[0]
    assert any("vol02" in x for x in CP.push_problems(ws))


def test_volume_override_reported_as_volume(tmp_path):
    ws = _ws(tmp_path, "", {"vol01": "id: vol01\ncorpus: 9\n"}, {"vol01": [1]})
    out = CP.unresolved_pins(ws)
    assert len(out) == 1 and "写在册 yaml" in out[0]


def test_no_ledger_falls_back_to_book_manifest(tmp_path):
    ws = _ws(tmp_path, "corpus: 1\n", {"01": "id: '01'\n"}, {})
    assert len(CP.unresolved_pins(ws)) == 1             # 没账、也没 v1 清单
    mp = CP.manifest_path(ws, 1)
    mp.parent.mkdir(parents=True)
    mp.write_text(json.dumps({"items": []}), encoding="utf-8")
    assert CP.unresolved_pins(ws) == []                 # 旧做法：总号即书库版本（史記现状）


def test_resolve_pin_message_mentions_defaults(tmp_path):
    ws = _ws(tmp_path, "", {}, {"vol02": [23]})
    with pytest.raises(FileNotFoundError, match="基础配置"):
        CP.resolve_pin(ws, "vol02", 25)
