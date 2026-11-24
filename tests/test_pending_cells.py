# -*- coding: utf-8 -*-
"""feedback/pending_cells：产物 → 待审格的纯函数入口（给 manager 收尾对账）。自造 seed_admit 与字块图。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from open_guji_cv.feedback import pending_cells as PC


def make_products(tmp_path: Path, n_review: int = 2) -> Path:
    seed = tmp_path / "products" / "vol01" / "seed_admit"
    seed.mkdir(parents=True)
    doc = {"seed_admit": {"n_review": n_review, "columns": [
        {"chars": [
            {"id": "vol01:1:1:1", "admit": True},
            {"id": "vol01:1:1:2", "admit": False, "doubts": ["lib_miss"]},
            {"id": "vol01:1:1:3", "admit": False, "doubts": ["excluded"], "evidence": {"excluded": "human:seg_defect"}},
        ]},
        {"chars": [{"id": "vol01:1:2:1a", "admit": False}]},
    ]}}
    (seed / "p0001.json").write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path / "products"


def patches(tmp_path: Path, shades: dict[str, int]):
    d = tmp_path / "patches"
    d.mkdir(exist_ok=True)
    out = {}
    for cell, v in shades.items():
        p = d / (cell.replace(":", "_") + ".png")
        Image.fromarray(np.full((40, 30), v, dtype=np.uint8)).save(p)
        out[cell] = p
    return out.get


def test_machine_pending_same_rule_as_pending_list(tmp_path):
    cells, n, every = PC.machine_pending(make_products(tmp_path), "vol01")
    assert cells == [{"cell": "1:1:2", "review": "pending"}, {"cell": "1:2:1a", "review": "pending"}]
    assert n == 2 and every == {"1:1:1", "1:1:2", "1:1:3", "1:2:1a"}


def test_fps_images_content_addressed_and_written(tmp_path):
    prod = make_products(tmp_path)
    read = patches(tmp_path, {"1:1:2": 10, "1:2:1a": 200})
    out = tmp_path / "out"
    r = PC.pending_cells(prod, "vol01", read_patch=read, out_dir=out)
    assert r["schema"] == PC.SCHEMA and r["no_image"] == [] and r["missing"] == []
    assert r["fps"]["1:1:2"] == hashlib.sha1(read("1:1:2").read_bytes()).hexdigest()
    names = {c["cell"]: c["img"]["s"] for c in r["cells"]}
    assert all(n.startswith("c") and n.endswith(".webp") for n in names.values())
    assert sorted(e["name"] for e in r["sprites"]) == sorted(set(names.values()))
    for e in r["sprites"]:
        assert hashlib.sha256((out / e["name"]).read_bytes()).hexdigest() == e["sha256"]
    assert r["cells"][0]["img"]["x"] == 0 and r["cells"][0]["img"]["w"] <= 96


def test_cell_doc_does_not_shift_when_neighbour_added(tmp_path):
    """整页雪碧图的坑：同页多一格，别的格坐标就挪。按内容寻址的单格图下，没变的格 doc 一字不变。"""
    prod = make_products(tmp_path)
    read = patches(tmp_path, {"1:1:2": 10, "1:2:1a": 200, "1:1:1": 90})
    a = PC.pending_cells(prod, "vol01", read_patch=read, images=True)
    b = PC.pending_cells(prod, "vol01", read_patch=read, images=True, extra=["vol01:1:1:1"])
    da = {c["cell"]: c for c in a["cells"]}
    db = {c["cell"]: c for c in b["cells"]}
    assert set(db) - set(da) == {"1:1:1"}
    for cell in da:
        assert da[cell] == db[cell]
    assert a["digest"] != b["digest"]
    assert PC.pending_cells(prod, "vol01", read_patch=read)["digest"] == a["digest"]


def test_extra_not_in_segmentation_goes_to_missing(tmp_path):
    r = PC.pending_cells(make_products(tmp_path), "vol01", read_patch=lambda c: None, extra=["9:9:9", "1:1:2"])
    assert r["missing"] == ["9:9:9"] and [c["cell"] for c in r["cells"]] == ["1:1:2", "1:2:1a"]
    assert r["no_image"] == ["1:1:2", "1:2:1a"] and r["fps"] == {} and "img" not in r["cells"][0]


def test_no_images_only_fingerprints(tmp_path):
    prod = make_products(tmp_path)
    r = PC.pending_cells(prod, "vol01", read_patch=patches(tmp_path, {"1:1:2": 10, "1:2:1a": 200}), images=False)
    assert len(r["fps"]) == 2 and r["sprites"] == [] and all("img" not in c for c in r["cells"])


def test_n_review_mismatch_raises_unless_not_strict(tmp_path):
    prod = make_products(tmp_path, n_review=5)
    with pytest.raises(ValueError):
        PC.pending_cells(prod, "vol01", read_patch=lambda c: None)
    assert len(PC.pending_cells(prod, "vol01", read_patch=lambda c: None, strict=False)["cells"]) == 2


def test_manager_api_exports(tmp_path):
    from open_guji_cv import manager_api
    assert manager_api.pending_cells is PC.pending_cells
