# -*- coding: utf-8 -*-
"""scripts/zhengli/republish.py（重跑后重发待审单，GUJI-680）：自造产物、线上单与人裁事件，不碰真书。"""
from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "zhengli" / "republish.py"
spec = importlib.util.spec_from_file_location("zhengli_republish", SCRIPT)
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)


def test_next_rev_and_ids(tmp_path):
    assert rp.next_rev("006-r2", "006") == "006-r3"
    assert rp.next_rev(None, "006") == "006-r0"
    assert rp.chapter_of("vol06") == "006"
    assert rp.text_id_of(tmp_path / "96mid1ogzk-欽定四庫全書總目") == "96mid1ogzk"
    assert sorted(["10:1:1", "2:3:4b", "2:3:4a", "2:10:1"], key=rp._key) == ["2:3:4a", "2:3:4b", "2:10:1", "10:1:1"]


def test_diff_explains_each_removed_cell():
    old = {"rev": "006-r2", "cells": [{"cell": c} for c in ("1:1:1", "1:1:2", "1:1:3", "1:1:4", "1:1:5")]}
    new = {"rev": "006-r3", "cells": [{"cell": "1:1:4"}, {"cell": "2:1:1", "cls": "near_form"}]}
    d = rp.diff(old, new, dropped=[{"cell": "1:1:1"}], states={"1:1:2": ("admit", "己"), "1:1:5": ("excluded", None)}, votes=Counter({"1:1:4": 2}))
    assert (d["old"], d["new"], d["kept"]) == (5, 2, 1)
    assert [(x["cell"], x["why"]) for x in d["removed"]] == [
        ("1:1:1", "人裁过"), ("1:1:2", "机器放行「己」"), ("1:1:3", "格号没了（多半重切）"), ("1:1:5", "排除名单（非字）")]
    assert d["added"] == [{"cell": "2:1:1", "cls": "near_form"}]
    assert d["votes_on_old"] == 2 and d["voted_cells_kept"] == ["1:1:4"]
    md = rp.diff_md("vol06", d, team=0, reflow=0)
    assert "006-r2 → 006-r3" in md and "精校票 2 张" in md


def _setup(tmp_path):
    """没迁中心库的工作区（数据根就是工作区）：一页产物、一张线上单、一条人裁事件、一份 cord。"""
    ws = tmp_path / "abc123-书"
    seed = ws / "products" / "vol06" / "seed_admit"
    seed.mkdir(parents=True)
    seed.joinpath("p0001.json").write_text(json.dumps({"seed_admit": {"n_review": 3, "columns": [{"chars": [
        {"id": "vol06:1:1:1", "admit": True, "char": "己"},
        {"id": "vol06:1:1:2", "admit": False, "doubts": ["lib_miss"]},
        {"id": "vol06:1:1:3", "admit": False},
        {"id": "vol06:1:1:4", "admit": False},
    ]}]}}), encoding="utf-8")
    online = ws / "feedback" / "lists" / "proofing" / "abc123" / "006.pending.json"
    online.parent.mkdir(parents=True)
    online.write_text(json.dumps({"rev": "006-r2", "cells": [{"cell": c, "review": "pending"} for c in
                                                             ("1:1:1", "1:1:2", "1:1:9")]}), encoding="utf-8")
    ev = ws / "feedback" / "events"
    ev.mkdir(parents=True)
    ev.joinpath("a.jsonl").write_text(json.dumps({"kind": "confirm", "ts": "2026-10-20T00:00:00Z",
                                                  "target": {"unit": "cell", "key": "vol06:1:1:3"},
                                                  "payload": {"v": "confirm", "shape": "甲"}}) + "\n", encoding="utf-8")
    export = ws / "reports" / "vol06" / "_export"
    export.mkdir(parents=True)
    export.joinpath("006.cord.json").write_text("{}", encoding="utf-8")
    return ws, export, online


def test_prep_then_push(tmp_path, monkeypatch, capsys):
    ws, export, online = _setup(tmp_path)
    monkeypatch.delenv("GUJI_PRODUCTS_DIR", raising=False)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    assert rp.main(["prep", "--book", "vol06", "-w", str(ws), "--export-dir", str(export),
                    "--no-alt", "--no-sprite", "--cv-commit", "abc1234"]) == 0
    out = ws / "reports" / "vol06" / "_publish" / "006-r3"
    new = json.loads((out / "006.pending.json").read_text(encoding="utf-8"))
    assert new["rev"] == "006-r3" and [c["cell"] for c in new["cells"]] == ["1:1:2", "1:1:4"]   # 1:1:3 人裁过，扣掉
    d = json.loads((out / "diff.json").read_text(encoding="utf-8"))
    assert {x["cell"]: x["why"] for x in d["removed"]} == {"1:1:1": "机器放行「己」", "1:1:9": "格号没了（多半重切）"}
    assert [x["cell"] for x in d["added"]] == ["1:1:4"]
    assert json.loads(online.read_text(encoding="utf-8"))["rev"] == "006-r2"                  # prep 不碰线上单

    with pytest.raises(SystemExit):                                                             # 不给 --yes 不推
        rp.main(["push", "--book", "vol06", "-w", str(ws), "--rev", "006-r3"])
    monkeypatch.setattr(rp, "run", lambda cmd, **kw: None)                                      # 台账脚本另有测试
    assert rp.main(["push", "--book", "vol06", "-w", str(ws), "--rev", "006-r3", "--yes"]) == 0
    assert json.loads(online.read_text(encoding="utf-8"))["rev"] == "006-r3"
    assert (out / "online.006-r2.pending.json").exists()
    assert "book-text" in capsys.readouterr().out
