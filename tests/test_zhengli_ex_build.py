# -*- coding: utf-8 -*-
"""scripts/zhengli/ex_build.py（GUJI-652 从 ai-team 迁入）：自造原图／cord／char／字形库，不碰真书与中心库。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "zhengli" / "ex_build.py"
spec = importlib.util.spec_from_file_location("zhengli_ex_build", SCRIPT)
eb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eb)

W, H = 200, 300
#: 本册各格现行字（char.json）：页 → [(格号, 字)]
TEXT = {
    1: [("1:1:1", "之")],
    2: [("2:1:1", "之"), ("2:1:2", "之")],
    3: [("3:1:1", "乎"), ("3:1:2", "之"), ("3:1:3", "之")],
    4: [("4:1:1", "之")],                      # 原图尺寸与 cord 不等的页
}


def jsonl(p: Path, rows):
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def make_inputs(tmp_path: Path, rev: str = "001-r1"):
    raw = tmp_path / "raw"
    (raw / "vol01").mkdir(parents=True)
    for pg in TEXT:
        Image.new("L", (W, H) if pg != 4 else (50, 50), 255).save(raw / "vol01" / f"{pg}.png")
    cord = {"pages": [{"page": pg, "image": {"width": W, "height": H},
                       "cells": [{"a": a, "box": [10, 10 + 50 * i, 40, 40]} for i, (a, _) in enumerate(cells)]}
                      for pg, cells in TEXT.items()]}
    char = {"pages": [{"page": pg, "columns": [{"cells": [{"a": a, "c": c} for a, c in cells]}]}
                      for pg, cells in TEXT.items()]}
    pend = {"rev": rev, "cells": [
        {"cell": "1:1:1", "review": "pending", "lib_top": [{"c": "之", "s": 0.9}], "ocr": [{"c": "乎"}, {"c": "之"}]},
    ]}
    store = tmp_path / "store"
    (store / "instances").mkdir(parents=True)
    inst = [
        {"instance_id": "vol01:1:1:1", "label": "之", "label_status": "human"},        # 本格自己
        {"instance_id": "vol01:2:1:2", "label": "之", "label_confidence": 0.9},         # 同页第二个，让位
        {"instance_id": "v2:vol01:2:1:1", "label": "之", "label_status": "human"},      # 人裁优先
        {"instance_id": "vol01:3:1:1", "label": "之", "label_status": "human"},         # 现行文本是「乎」
        {"instance_id": "vol01:3:1:2", "label": "之", "label_status": "human"},         # 撤了
        {"instance_id": "vol01:3:1:3", "label": "之", "label_confidence": 0.5},
        {"instance_id": "vol01:4:1:1", "label": "之", "label_status": "human"},         # 尺寸不等的页
        {"instance_id": "vol02:2:1:1", "label": "之", "label_status": "human"},         # 别册
        {"instance_id": "vol01:9:9:9", "label": "之"},                                   # 没放行
    ]
    jsonl(store / "instances" / "vol01.jsonl", inst)
    jsonl(store / "admissions.jsonl", [{"instance_id": r["instance_id"], "char": "之"}
                                       for r in inst if r["instance_id"] != "vol01:9:9:9"])
    jsonl(store / "evictions.jsonl", [{"instance_id": "vol01:3:1:2"}])
    for name, doc in (("001.cord.json", cord), ("001.char.json", char), ("001.pending.json", pend)):
        (tmp_path / name).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return raw, store


def run(tmp_path, raw, store, out):
    return eb.main(["--pending", str(tmp_path / "001.pending.json"), "--cord", str(tmp_path / "001.cord.json"),
                    "--char", str(tmp_path / "001.char.json"), "--store", str(store), "--raw-root", str(raw),
                    "--chapter", "001", "--out", str(out), "--book", "vol01"])


def test_examples_pick_rules_and_positions(tmp_path):
    raw, store = make_inputs(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    assert run(tmp_path, raw, store, out) == 0
    [cell] = json.loads((out / "pending.with-ex.json").read_text(encoding="utf-8"))["cells"]
    # 只有「之」有例子：人裁的 2:1:1 在前，3:1:3 在后；「乎」没例子不出键
    assert list(cell["ex"]) == ["之"]
    assert cell["ex"]["之"] == [{"s": "ex-001.webp", "x": 0, "y": 0, "w": 96, "h": 96},
                               {"s": "ex-001.webp", "x": 96, "y": 0, "w": 96, "h": 96}]
    assert Image.open(out / "ex-001.webp").size == (2 * eb.TILE, eb.TILE)


def test_assets_json_ex_entries_replaced_and_rev_checked(tmp_path):
    raw, store = make_inputs(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "assets.json").write_text(json.dumps(
        {"rev": "001-r1", "files": [{"name": "p0001.webp"}, {"name": "ex-001.webp", "bytes": 1}]}), encoding="utf-8")
    run(tmp_path, raw, store, out)
    files = json.loads((out / "assets.json").read_text(encoding="utf-8"))["files"]
    assert [f["name"] for f in files] == ["p0001.webp", "ex-001.webp"]
    assert files[1]["bytes"] == (out / "ex-001.webp").stat().st_size

    (out / "assets.json").write_text(json.dumps({"rev": "001-r0", "files": []}), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        run(tmp_path, raw, store, out)
    assert "不一致" in str(e.value.code)


def test_cell_chars_dedupes_in_candidate_order():
    c = {"lib_top": [{"c": "甲"}, {"c": "乙"}, {"c": "丙"}, {"c": "丁"}], "ocr": [{"c": "乙"}, {"c": "戊"}],
         "ref": {"c": "己"}, "ctx": {"c": ""}}
    assert eb.cell_chars(c) == ["甲", "乙", "丙", "戊", "己"]


def test_cell_of_and_rank():
    assert eb.cell_of("v2:vol01:3:4:5a", "vol01") == "3:4:5a"
    assert eb.cell_of("vol01:3:4:5", "vol01") == "3:4:5"
    assert eb.cell_of("vol010:3:4:5", "vol01") is None
    rows = [{"instance_id": "b", "label_confidence": 0.9}, {"instance_id": "a", "label_status": "human"},
            {"instance_id": "c", "label_confidence": 0.95}]
    assert [r["instance_id"] for r in sorted(rows, key=eb.rank)] == ["a", "c", "b"]
