# -*- coding: utf-8 -*-
"""scripts/zhengli/sprite_build.py（GUJI-652 从 ai-team 迁入）：自造原图／cord／pending，不碰真书。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "zhengli" / "sprite_build.py"
spec = importlib.util.spec_from_file_location("zhengli_sprite_build", SCRIPT)
sb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sb)


def make_inputs(tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    im = Image.new("L", (200, 300), 255)
    im.paste(0, (20, 20, 40, 40))
    im.save(raw / "1.png")
    Image.new("L", (100, 100), 255).save(raw / "2.png")     # 与 cord 页图尺寸不等
    cord = {"pages": [
        {"page": 1, "image": {"width": 200, "height": 300},
         "cells": [{"a": "1:1:1", "box": [10, 10, 40, 40]}, {"a": "1:1:2", "box": [10, 60, 40, 40]},
                   {"a": "1:1:3", "box": None}]},
        {"page": 2, "image": {"width": 200, "height": 300}, "cells": [{"a": "2:1:1", "box": [0, 0, 10, 10]}]},
    ]}
    pend = {"rev": "001-r1", "cv_version": None, "cv_commit": "x",
            "cells": [{"cell": c, "review": "pending"} for c in ("1:1:1", "1:1:2", "1:1:3", "2:1:1", "9:9:9")]}
    (tmp_path / "001.cord.json").write_text(json.dumps(cord), encoding="utf-8")
    (tmp_path / "001.pending.json").write_text(json.dumps(pend), encoding="utf-8")
    return raw


def run(tmp_path, raw, out):
    return sb.main(["--cord", str(tmp_path / "001.cord.json"), "--pending", str(tmp_path / "001.pending.json"),
                    "--raw-dir", str(raw), "--book", "96mid1ogzk", "--vol", "01", "--out", str(out)])


def test_sprite_sheet_assets_and_img_fields(tmp_path):
    raw = make_inputs(tmp_path)
    out = tmp_path / "out"
    assert run(tmp_path, raw, out) == 0

    sheet = out / "p0001.webp"
    assert sheet.is_file()
    assert Image.open(sheet).size == (2 * sb.TILE, sb.TILE)
    man = json.loads((out / "assets.json").read_text(encoding="utf-8"))
    assert man["schema"] == "guji-proof-assets/0.1"
    assert (man["book"], man["volume"], man["rev"]) == ("96mid1ogzk", 1, "001-r1")
    [f] = man["files"]
    raw_bytes = sheet.read_bytes()
    assert f == {"name": "p0001.webp", "bytes": len(raw_bytes), "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                 "w": 2 * sb.TILE, "h": sb.TILE}

    cells = {c["cell"]: c for c in json.loads((out / "pending.with-img.json").read_text(encoding="utf-8"))["cells"]}
    assert cells["1:1:1"]["img"] == {"s": "p0001.webp", "x": 0, "y": 0, "w": 96, "h": 96}
    assert cells["1:1:2"]["img"]["x"] == 96
    # 无框、无 cord 格、原图尺寸对不上的页：都不出 img，也不瞎裁
    for c in ("1:1:3", "2:1:1", "9:9:9"):
        assert "img" not in cells[c]
    assert not (out / "p0002.webp").exists()


def test_tile_of_is_tile_sized_and_pads_within_image():
    im = Image.new("L", (50, 80), 255)
    t = sb.tile_of(im, [0, 0, 50, 20], 0.5)          # 外扩出界也只裁到图边
    assert t.size == (sb.TILE, sb.TILE) and t.mode == "L"
    assert sb.COLS == 2048 // sb.TILE
