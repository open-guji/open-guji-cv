# -*- coding: utf-8 -*-
"""`guji book show --effective` 的字形库来源（2026-11-03）：借库（workspace.yaml glyph_lib.borrow）与钉版快照。"""
from __future__ import annotations

import json
from types import SimpleNamespace

from open_guji_cv.core.glyph_pin import glyph_sources


def _ws(tmp_path, borrow):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "workspace.yaml").write_text("glyph_lib:\n  borrow:\n" + "".join(f"    - {b}\n" for b in borrow),
                                       encoding="utf-8")
    return ws


def test_unpinned_lists_borrow(tmp_path):
    ws = _ws(tmp_path, ["../lib/output/glyph_store"])
    lib = tmp_path / "lib"
    (lib / "output" / "glyph_store").mkdir(parents=True)
    (lib / ".borrowed-state.json").write_text(json.dumps({"rev": 812}), encoding="utf-8")
    g = glyph_sources(SimpleNamespace(glyph_pin=None), ws)
    assert g["effective"] == "local" and g["pin"] is None
    assert g["borrow"] == [{"entry": "../lib/output/glyph_store", "path": str(ws / "../lib/output/glyph_store"),
                            "local_rev": 812}]


def test_pinned_snapshot_counts_borrowed_files(tmp_path):
    ws = _ws(tmp_path, ["glyphlib-qkp-v1"])
    man = ws / "config" / "glyph-pack" / "g3"
    man.mkdir(parents=True)
    items = [{"root": "gs", "path": "a.json", "sha256": "1"},
             {"root": "borrow:glyphlib-qkp-v1", "path": "b.json", "sha256": "2"},
             {"root": "borrow:glyphlib-qkp-v1", "path": "c.json", "sha256": "3"}]
    (man / "manifest.json").write_text(json.dumps({"digest": "glyph-x", "items": items}), encoding="utf-8")
    g = glyph_sources(SimpleNamespace(glyph_pin=3), ws)
    assert g["effective"] == "pinned" and g["pin"]["n"] == 3
    assert g["pinned_borrow"] == {"glyphlib-qkp-v1": 2}
    assert g["borrow"][0]["local_rev"] is None


def test_no_borrow(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert glyph_sources(SimpleNamespace(glyph_pin=None), ws)["borrow"] == []
