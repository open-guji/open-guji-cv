# -*- coding: utf-8 -*-
"""scripts/zhengli/alt_build.py（GUJI-652 从 ai-team 迁入）：自造 pending（带 alt），字体用本仓 fonts/ 或假渲染器。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import open_guji_cv.clustering.glyph_selfcheck as gs

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "zhengli" / "alt_build.py"
spec = importlib.util.spec_from_file_location("zhengli_alt_build", SCRIPT)
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)


class FakeRenderer:
    """只会画 `chars` 里的字：256² 白底中间一块黑。"""

    def __init__(self, chars: str):
        self.chars = chars

    def render(self, ch):
        if ch not in self.chars:
            return None
        a = np.full((256, 256), 255, np.uint8)
        a[60:200, 90:160] = 0
        return a


def write_pending(tmp_path: Path, rev: str = "001-r1") -> Path:
    pend = {"rev": rev, "cv_version": None, "cv_commit": "x", "cells": [
        {"cell": "1:1:1", "review": "pending", "alt": [{"c": "之", "s": 0.9}, {"c": "乎", "s": 0.8}]},
        {"cell": "1:1:2", "review": "pending", "alt": [{"c": "之", "s": 0.7}, {"c": "无", "s": 0.1}]},
        {"cell": "1:1:3", "review": "pending"},
    ]}
    p = tmp_path / "001.pending.json"
    p.write_text(json.dumps(pend, ensure_ascii=False), encoding="utf-8")
    return p


def run(pending: Path, out: Path):
    return ab.main(["--pending", str(pending), "--chapter", "001", "--out", str(out)])


def test_alt_glyphs_get_positions_and_missing_chars_stay_text(tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "font_renderer", lambda f: FakeRenderer("之" if f == "iming" else "之乎"))
    out = tmp_path / "out"
    assert run(write_pending(tmp_path), out) == 0

    sheet = out / "alt-001.webp"
    assert Image.open(sheet).size == (2 * ab.TILE, ab.TILE)          # 之、乎 两格；「无」两套都没有
    cells = json.loads((out / "pending.with-alt.json").read_text(encoding="utf-8"))["cells"]
    a, b, c = cells
    assert a["alt"][0]["g"] == {"s": "alt-001.webp", "x": 0, "y": 0, "w": 96, "h": 96}
    assert a["alt"][1]["g"]["x"] == 96 and a["alt"][1]["s"] == 0.8   # 原字段保留
    assert b["alt"][0]["g"]["x"] == 0                                # 同字共用一格
    assert "g" not in b["alt"][1]                                     # 没图的字不加 g
    assert "alt" not in c
    # 没有现成 assets.json 时不新建（只往 sprite_build 出的清单里追加）
    assert not (out / "assets.json").exists()


def test_assets_json_alt_entries_replaced_others_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "font_renderer", lambda f: FakeRenderer("之乎"))
    out = tmp_path / "out"
    out.mkdir()
    old = {"schema": "guji-proof-assets/0.1", "book": "b", "volume": 1, "rev": "001-r1",
           "files": [{"name": "p0001.webp"}, {"name": "alt-001.webp"}, {"name": "alt-001-b.webp"},
                     {"name": "alt-002.webp"}]}
    (out / "assets.json").write_text(json.dumps(old), encoding="utf-8")
    run(write_pending(tmp_path), out)
    man = json.loads((out / "assets.json").read_text(encoding="utf-8"))
    names = [f["name"] for f in man["files"]]
    assert names == ["p0001.webp", "alt-002.webp", "alt-001.webp"]
    assert man["files"][-1]["bytes"] == (out / "alt-001.webp").stat().st_size


def test_assets_rev_mismatch_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "font_renderer", lambda f: FakeRenderer("之"))
    out = tmp_path / "out"
    out.mkdir()
    (out / "assets.json").write_text(json.dumps({"rev": "001-r0", "files": []}), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        run(write_pending(tmp_path), out)
    assert "不一致" in str(e.value.code)


def test_no_fonts_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "font_renderer", lambda f: False)
    with pytest.raises(SystemExit) as e:
        run(write_pending(tmp_path), tmp_path / "out")
    assert "找不到" in str(e.value.code)


def test_real_repo_fonts_render_common_char(tmp_path):
    """不打桩：缺省 --cv-root＝本仓，字体取本仓 fonts/（在 git 里）。"""
    if not gs.font_renderer("iming") and not gs.font_renderer("jigmo"):
        pytest.skip("本仓 fonts/ 下没有 I.Ming／Jigmo")
    out = tmp_path / "out"
    assert run(write_pending(tmp_path), out) == 0
    a = json.loads((out / "pending.with-alt.json").read_text(encoding="utf-8"))["cells"][0]
    assert "g" in a["alt"][0]
    tile = Image.open(out / "alt-001.webp").convert("L").crop((0, 0, 96, 96))
    assert tile.getextrema()[0] < 128                                # 真有墨


def test_glyph_tile_centres_ink():
    a = np.full((256, 256), 255, np.uint8)
    a[0:10, 0:10] = 0
    t = ab.glyph_tile(a)
    assert t.size == (ab.TILE, ab.TILE)
    assert t.getpixel((48, 48)) < 128 and t.getpixel((2, 2)) == 255
