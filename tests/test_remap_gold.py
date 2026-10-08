# -*- coding: utf-8 -*-
"""research/y1_admit/remap_gold.py：整册重跑后格框变了，金标按 IoU 一对一重映射。数据全是自造的。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "research" / "y1_admit" / "remap_gold.py"
_spec = importlib.util.spec_from_file_location("remap_gold", _SRC)
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

B = "bk"


def _box(x, y, w=100, h=100):
    return [float(x), float(y), float(x + w), float(y + h)]


def _write(prod, step, pages):
    """pages = {页号: [(id, bbox) 或 (id, bbox, extra)]}"""
    for pg, cells in pages.items():
        d = Path(prod, B, step)
        d.mkdir(parents=True, exist_ok=True)
        chars = []
        for c in cells:
            r = {"id": c[0], "bbox_page": c[1]} if step == "cell_shrink" else {"id": c[0], **c[2]}
            chars.append(r)
        (d / f"p{pg:04d}.json").write_text(json.dumps({"x": {"page": pg, "columns": [{"chars": chars}]}}), encoding="utf-8")


def _gold(cell, v, shown, char=None):
    return {"cell": cell, "v": v, "shown": shown, **({"char": char} if char else {})}


def test_iou_basic():
    assert rg.iou(_box(0, 0), _box(0, 0)) == 1.0
    assert rg.iou(_box(0, 0), _box(200, 0)) == 0.0
    assert rg.iou(_box(0, 0), _box(50, 0)) == pytest.approx(1 / 3)


def test_remap_shift_unchanged_failed_and_conflict():
    old = {1: {f"{B}:1:1:1": _box(0, 0), f"{B}:1:1:2": _box(0, 100), f"{B}:1:1:3": _box(0, 200),
               f"{B}:1:1:4": _box(0, 300)}}
    # 新产物：第 2 格被切成两块、格号整体错位；原 1 号框不变；原 4 号框没有对应新格
    new = {1: {f"{B}:1:1:1": _box(0, 0),
               f"{B}:1:1:2": _box(0, 100, h=40),     # 与旧 2 号 IoU 0.4：不够
               f"{B}:1:1:5": _box(0, 205),            # 旧 3 号 → 5 号
               f"{B}:1:1:9": _box(500, 0)}}
    gold = [_gold(f"{B}:1:1:1", "ok", "天"), _gold(f"{B}:1:1:2", "ok", "地"),
            _gold(f"{B}:1:1:3", "wrong", "玄", "黃"), _gold(f"{B}:1:1:4", "ok", "宇")]
    mapped, failed, unchanged = rg.remap(gold, old, new, 0.5)
    got = {m["cell"]: m for m in mapped}
    assert set(got) == {f"{B}:1:1:1", f"{B}:1:1:5"} and unchanged == 1
    assert got[f"{B}:1:1:5"]["cell_old"] == f"{B}:1:1:3" and got[f"{B}:1:1:5"]["char"] == "黃"
    assert dict(failed) == {f"{B}:1:1:2": "no_overlap", f"{B}:1:1:4": "no_overlap"}


def test_one_to_one_larger_iou_wins():
    old = {1: {f"{B}:1:1:1": _box(0, 0), f"{B}:1:1:2": _box(0, 30)}}
    new = {1: {f"{B}:1:1:7": _box(0, 10)}}          # 对旧 1 号 IoU 0.82，对旧 2 号 0.54：都过线，只许一个
    gold = [_gold(f"{B}:1:1:1", "ok", "a"), _gold(f"{B}:1:1:2", "ok", "b")]
    mapped, failed, _ = rg.remap(gold, old, new, 0.5)
    assert [m["cell_old"] for m in mapped] == [f"{B}:1:1:1"]
    assert failed == [(f"{B}:1:1:2", "lost_to_other")]


def test_missing_old_box_and_new_page():
    old = {1: {f"{B}:1:1:1": _box(0, 0)}}
    gold = [_gold(f"{B}:1:1:1", "ok", "a"), _gold(f"{B}:1:1:8", "ok", "b"), _gold(f"{B}:2:1:1", "ok", "c")]
    mapped, failed, _ = rg.remap(gold, old, {}, 0.5)
    assert mapped == []
    assert dict(failed) == {f"{B}:1:1:1": "no_new_page", f"{B}:1:1:8": "no_old_box", f"{B}:2:1:1": "no_old_box"}


def test_report_counts_false_admits(tmp_path):
    old_p, new_p = tmp_path / "old", tmp_path / "new"
    _write(old_p, "cell_shrink", {1: [(f"{B}:1:1:1", _box(0, 0)), (f"{B}:1:1:2", _box(0, 100)),
                                     (f"{B}:1:1:3", _box(0, 200)), (f"{B}:1:1:4", _box(0, 300))]})
    _write(new_p, "cell_shrink", {1: [(f"{B}:1:1:1", _box(0, 0)), (f"{B}:1:1:6", _box(0, 102)),
                                      (f"{B}:1:1:7", _box(0, 203)), (f"{B}:1:1:9", _box(0, 303))]})
    _write(new_p, "seed_admit", {1: [(f"{B}:1:1:1", None, {"admit": True, "char": "天"}),
                                      (f"{B}:1:1:6", None, {"admit": True, "char": "他"}),     # 金标 地 → 误放行
                                      (f"{B}:1:1:7", None, {"admit": False, "char": "玄"}),    # 待审，不算
                                      ]})
    gold_f = tmp_path / "g.jsonl"
    gold_f.write_text("".join(json.dumps(g, ensure_ascii=False) + "\n" for g in [
        _gold(f"{B}:1:1:1", "ok", "天"), _gold(f"{B}:1:1:2", "ok", "地"),
        _gold(f"{B}:1:1:3", "wrong", "玄", "黃"), _gold(f"{B}:1:1:4", "unsure", "?")]), encoding="utf-8")
    out, rep_f = tmp_path / "o.jsonl", tmp_path / "r.json"
    rep = rg.main(["--book", B, "--gold", str(gold_f), "--old-products", str(old_p), "--new-products", str(new_p),
                   "--out", str(out), "--report", str(rep_f)])
    assert rep["gold_total"] == 4 and rep["mapped"] == 4 and rep["unchanged_id"] == 1 and rep["unmapped"] == 0
    ca = rep["checked_admit"]
    assert ca["admitted_right"] == 1 and ca["false_admit"] == 1 and ca["no_seed_record"] == 0
    assert ca["false_admit_cells"][0]["cell"] == f"{B}:1:1:6" and ca["false_admit_cells"][0]["cell_old"] == f"{B}:1:1:2"
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert {r["cell"] for r in rows} == {f"{B}:1:1:1", f"{B}:1:1:6", f"{B}:1:1:7", f"{B}:1:1:9"}
    assert json.loads(rep_f.read_text(encoding="utf-8"))["mapped"] == 4
