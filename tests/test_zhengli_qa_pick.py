# -*- coding: utf-8 -*-
"""scripts/zhengli/qa_pick.py（GUJI-693）：自造 seed_admit／cord／原图，不碰真书。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "zhengli" / "qa_pick.py"
spec = importlib.util.spec_from_file_location("zhengli_qa_pick", SCRIPT)
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)


def make(tmp_path: Path) -> tuple[Path, Path, Path]:
    seed = tmp_path / "products" / "vol05" / "seed_admit"
    seed.mkdir(parents=True)
    chars = [
        {"id": "vol05:3:1:1", "slot": 1, "admit": True, "channel": "rare_ref", "char": "上", "evidence": {"cov": 0.9}},
        {"id": "vol05:3:1:2", "slot": 2, "admit": True, "channel": "rare_ref", "char": "且", "evidence": {"cov": 0.5}},
        {"id": "vol05:3:1:3", "slot": 3, "admit": True, "channel": "rare_ref", "char": "下", "evidence": {"cov": 0.7}},
        {"id": "vol05:3:1:4", "slot": 4, "admit": True, "channel": "context", "char": "今",
         "evidence": {"cov": 0.1, "ctx_margin": 0.8}},
        {"id": "vol05:3:1:5", "slot": 5, "admit": True, "channel": "context", "char": "古",
         "evidence": {"cov": 0.9, "ctx_margin": 0.2}},
        {"id": "vol05:3:1:6", "slot": 6, "admit": True, "channel": "witness3", "char": "巡",
         "evidence": {"lane": {"lane": "witness3", "cov": 0.3}}},
        {"id": "vol05:3:1:7", "slot": 7, "admit": True, "channel": "human", "char": "廵"},
        {"id": "vol05:3:1:8", "slot": 8, "admit": False, "doubts": ["lib_miss"]},
        {"id": "vol05:3:1:9", "slot": 9, "admit": True, "channel": "rare_ref", "char": "子", "doubts": ["excluded"]},
        {"id": "vol05:3:1:10", "slot": 10, "admit": True, "channel": "dual", "char": "之", "evidence": {"cov": 0.0}},
    ]
    (seed / "p0003.json").write_text(json.dumps({"seed_admit": {"page": 3, "columns": [{"col": 1, "chars": chars}]}},
                                                ensure_ascii=False), encoding="utf-8")
    cord = tmp_path / "005.cord.json"
    cord.write_text(json.dumps({"pages": [{"page": 3, "cells": [
        {"a": f"3:1:{i}", "id": f"vol05:3:1:{i}", "box": [10, 10 + 30 * i, 25, 25]} for i in range(1, 11)]}]}),
        encoding="utf-8")
    raw = tmp_path / "raw"
    raw.mkdir()
    Image.new("L", (100, 400), 200).save(raw / "3.png")
    return tmp_path / "products", cord, raw


def test_pick_lowest_confidence_per_channel(tmp_path):
    prod, cord, raw = make(tmp_path)
    out = tmp_path / "out"
    assert qa.main(["pick", "--book", "vol05", "--products", str(prod), "--cord", str(cord), "--raw-dir", str(raw),
                    "--out", str(out), "--quota", "rare_ref=2", "--quota", "context=1", "--quota", "witness3=1",
                    "--text-sha", "abc"]) == 0
    s = json.loads((out / "样本.json").read_text(encoding="utf-8"))
    # rare_ref 取 cov 最低两格；context 按 ctx_margin；witness3 的 cov 在 evidence.lane；人裁、排除、待审、没配额的 dual 不挑
    assert [c["a"] for c in s["cells"]] == ["3:1:2", "3:1:3", "3:1:5", "3:1:6"]
    assert [c["n"] for c in s["cells"]] == [1, 2, 3, 4]
    assert s["cells"][0]["box"] == [10, 70, 25, 25] and s["pool"]["dual"] == 1
    assert (out / "sheet01.png").exists() and "| 3 | 3:1:5 | context | 古 | 0.2 |" in (out / "清单.md").read_text(encoding="utf-8")
    # 复跑：样本 id 一样
    out2 = tmp_path / "out2"
    qa.main(["pick", "--book", "vol05", "--products", str(prod), "--out", str(out2), "--quota", "rare_ref=2",
             "--quota", "context=1", "--quota", "witness3=1", "--text-sha", "abc"])
    assert json.loads((out2 / "样本.json").read_text(encoding="utf-8"))["id"] == s["id"]


def test_cap_below_200(tmp_path):
    prod, _, _ = make(tmp_path)
    with pytest.raises(SystemExit):
        qa.main(["pick", "--book", "vol05", "--products", str(prod), "--out", str(tmp_path / "o"), "--max", "200"])


def test_tally(tmp_path):
    prod, cord, _ = make(tmp_path)
    out = tmp_path / "out"
    qa.main(["pick", "--book", "vol05", "--products", str(prod), "--cord", str(cord), "--out", str(out)])
    v = tmp_path / "判.tsv"
    v.write_text("n\t判\t类型\t扩查\t备注\n1\t对\n2\t错\t异体码位\t是\t廵\n3\t看不出\n", encoding="utf-8")
    assert qa.main(["tally", "--sample", str(out / "样本.json"), "--verdicts", str(v), "--judge", "sheldon"]) == 0
    rows = [json.loads(x) for x in (out / "qa.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 6 and rows[1]["verdict"] == "错" and rows[1]["type"] == "异体码位" and rows[1]["expanded"] is True
    assert sum(1 for r in rows if r["verdict"] is None) == 3
    md = (out / "汇总.md").read_text(encoding="utf-8")
    assert "错 1，看不出 1" in md and "| 异体码位 | 1 |" in md
    bad = tmp_path / "bad.tsv"
    bad.write_text("n\t判\t类型\n1\t错\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        qa.main(["tally", "--sample", str(out / "样本.json"), "--verdicts", str(bad), "--judge", "x"])
