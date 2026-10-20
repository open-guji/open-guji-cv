# -*- coding: utf-8 -*-
"""scripts/zhengli/known_errors.py（GUJI-684 已知错单）：自造数据，不碰真书。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

KE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "zhengli" / "known_errors.py"
spec = importlib.util.spec_from_file_location("known_errors_under_test", KE_PATH)
ke = importlib.util.module_from_spec(spec)
sys.modules["known_errors_under_test"] = ke
spec.loader.exec_module(ke)

TABLE = """# 总表
## 一、列表
| 格号 | 放的字 | 应为 | 来源 | 是否 iron | 窗口 | 要不要给 Eliot |
|---|---|---|---|---|---|---|
| vol01:72:9:9 | 宮 | 官（稗官） | x | 是 | 否 | 要 |
| vol06:40:1:1 | 一 | 非字（疑列首框线） | x | 是 | 否 | 要 |
| vol02:15:9:20 | 元（下半） | 待审（半字） | x | 待证据 | 否 | 要 |
| vol02:188:5:19 | 曰 | 对 | x | 否 | — | 否（撤出） |
## 二、注
| vol09:1:1:1 | 甲 | 乙 | x | 否 | 否 | 要 |
"""


def _char_json(path: Path, cells: dict[str, str]) -> None:
    cols: dict[tuple[int, int], list] = {}
    for a, c in cells.items():
        p, col, _ = a.split(":", 2)
        cols.setdefault((int(p), int(col)), []).append({"a": a, "c": c})
    pages: dict[int, list] = {}
    for (p, col), cs in cols.items():
        pages.setdefault(p, []).append({"col": col, "cells": cs})
    path.write_text(json.dumps({"pages": [{"page": p, "columns": c} for p, c in pages.items()]},
                               ensure_ascii=False), encoding="utf-8")


def test_parse_table_kinds_and_skips(tmp_path):
    t = tmp_path / "t.md"
    t.write_text(TABLE, encoding="utf-8")
    rows = {r["cell"]: r for r in ke.parse_table(t)}
    assert set(rows) == {"vol01:72:9:9", "vol06:40:1:1", "vol02:15:9:20"}   # 「否」撤出、第二节不收
    assert rows["vol01:72:9:9"]["expect"] == "官" and rows["vol01:72:9:9"]["kind"] == "char"
    assert rows["vol06:40:1:1"]["kind"] == "nonchar"
    assert rows["vol02:15:9:20"]["kind"] == "review" and rows["vol02:15:9:20"]["shown"] == "元"


def test_parse_vision_latest_wrong_only(tmp_path):
    v = tmp_path / "看图结论.jsonl"
    v.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in [
        {"cell": "vol04:1:1:1", "v": "wrong", "shown": "千", "char": "干", "judge": "m", "ts": "2026-10-01T00:00:00Z"},
        {"cell": "vol04:1:1:2", "v": "wrong", "shown": "一", "judge": "m", "note": "[S8] 非字（碎块）", "ts": "2026-10-01T00:00:00Z"},
        {"cell": "vol04:1:1:3", "v": "wrong", "shown": "中", "judge": "m", "ts": "2026-10-01T00:00:00Z"},
        {"cell": "vol04:1:1:3", "v": "ok", "shown": "中", "judge": "m", "ts": "2026-10-02T00:00:00Z"},
    ]), encoding="utf-8")
    rows = {r["cell"]: r for r in ke.parse_vision(v)}
    assert set(rows) == {"vol04:1:1:1", "vol04:1:1:2"}      # 后到的 ok 覆盖了 wrong
    assert rows["vol04:1:1:1"]["kind"] == "char" and rows["vol04:1:1:1"]["expect"] == "干"
    assert rows["vol04:1:1:2"]["kind"] == "nonchar"
    assert rows["vol04:1:1:1"]["source"].startswith("vision:")


def test_merge_prefers_human_source():
    rows = ke.merge([
        {"cell": "vol04:1:1:1", "shown": "千", "expect": "干", "kind": "char", "source": "vision:m:x", "note": ""},
        {"cell": "vol04:1:1:1", "shown": "千", "expect": "干", "kind": "char", "source": "总表.md", "note": ""},
        {"cell": "bad-id", "shown": "", "expect": "", "kind": "char", "source": "x", "note": ""},
    ])
    assert len(rows) == 1 and rows[0]["source"].startswith("总表.md")


def test_check_classifies(tmp_path):
    text = tmp_path / "default"
    text.mkdir()
    _char_json(text / "001.char.json", {"72:9:9": "宮", "72:9:10": "官", "72:9:11": "甲", "72:9:12": "□"})
    lst = tmp_path / "ke.tsv"
    ke.write_tsv([
        {"cell": "vol01:72:9:9", "shown": "宮", "expect": "官", "kind": "char", "source": "s", "note": ""},
        {"cell": "vol01:72:9:10", "shown": "宮", "expect": "官", "kind": "char", "source": "s", "note": ""},
        {"cell": "vol01:72:9:11", "shown": "宮", "expect": "官", "kind": "char", "source": "s", "note": ""},
        {"cell": "vol01:72:9:12", "shown": "一", "expect": "", "kind": "nonchar", "source": "s", "note": ""},
        {"cell": "vol01:99:1:1", "shown": "宮", "expect": "官", "kind": "char", "source": "s", "note": ""},
    ], lst)
    out = tmp_path / "r.json"
    rc = ke.main(["check", "--list", str(lst), "--text-dir", str(text), "--json", str(out), "--strict"])
    res = {r["cell"]: r["result"] for r in json.loads(out.read_text(encoding="utf-8"))}
    assert res == {"vol01:72:9:9": "still_wrong", "vol01:72:9:10": "fixed", "vol01:72:9:11": "changed",
                   "vol01:72:9:12": "fixed", "vol01:99:1:1": "missing"}
    assert rc == 3
