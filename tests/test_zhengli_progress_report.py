# -*- coding: utf-8 -*-
"""scripts/zhengli/progress_report.py（精校进度写后台「文本整理」）：只测口径，不连库不连网。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "zhengli"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("zl_progress_report", SCRIPTS / "progress_report.py")
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)


def ev(cell, shape="字", v="confirm", source=None, book="vol06"):
    p, c, s = cell.split(":")
    pl = {"v": v, "shape": shape}
    if source:
        pl["source"] = source
    return {"kind": "confirm", "target": {"unit": "cell", "book": book, "key": f"{book}:{cell}",
                                          "page": int(p), "col": int(c), "slot": int(s)}, "payload": pl}


CHAR = {"pages": [{"columns": [{"cells": [{"a": f"1:1:{i}", "c": "字"} for i in range(1, 11)]}]}]}


def test_counts_and_rate():
    sheet = {"rev": "006-r5", "routed_as_of": "2026-10-24T03:29:13Z",
             "cells": [{"cell": "1:1:1", "review": "pending"}, {"cell": "1:1:2", "review": "pending"},
                       {"cell": "1:1:9", "review": "human"}]}
    events = [ev("1:1:1"), ev("1:1:3"), ev("1:1:4"), ev("9:9:9"),            # 9:9:9 不在现行文本里（格号漂了）
              ev("1:1:5", source="vision"),                                  # 机器意见不算人裁
              {"kind": "comment", "target": {}, "payload": {}}]
    res = pr.compute("vol06", sheet, events, CHAR, {"text_version": "0.4.0"}, None, None)
    f = res["fields"]
    assert f["pending_review"] == 2 and f["pending_rev"] == "006-r5"
    assert f["human_judged"] == 3 and f["cells_total"] == 10
    assert f["extra"]["a32_judged_drifted"] == 1
    assert f["stage"] == "fine"
    rate = dict((m[0], m[2]) for m in res["metrics"])["review_rate"]
    assert rate == round(2 / 4, 4)          # 裁完 3,4（1 还在单上）÷ 已裁∪待审 {1,2,3,4}
    assert "006-r5 剩 2 格" in f["note"]


def test_frozen_and_manual_note():
    res = pr.compute("vol05", {"rev": "005-r10", "cells": [{"cell": "1:1:1"}]}, [], CHAR,
                     {"text_version": "1.0.1"}, {"freeze": {"at": "1.0.1"}}, "等 GUJI-743")
    f = res["fields"]
    assert f["stage"] == "released"
    assert f["note"].startswith("已冻结 1.0.1") and f["note"].endswith("等 GUJI-743")
    assert f["extra"]["a32_note"] == "等 GUJI-743"


def test_no_char_skips_cells_total():
    res = pr.compute("vol04", None, [ev("1:1:1", book="vol04")], None, None, None, None)
    assert "cells_total" not in res["fields"] and res["fields"]["human_judged"] == 1
    assert res["fields"]["pending_review"] == 0


def test_hook_only_a32_books(monkeypatch):
    called = []
    monkeypatch.setattr(pr, "run", lambda books, **kw: called.append(books))
    pr.try_run("vol09")
    pr.try_run("vol06")
    assert called == [["vol06"]]


def test_text_base():
    assert pr.text_base("96mid1ogzk") == "Book/g/z/k/96mid1ogzk/default"


def test_pending_drops_judged_since_issue_and_gone():
    sheet = {"rev": "006-r5", "routed_as_of": "2026-10-24T03:29:13Z",
             "cells": [{"cell": "1:1:1"}, {"cell": "1:1:2"}, {"cell": "1:1:3"}, {"cell": "7:7:7"}]}
    old, new = ev("1:1:1"), ev("1:1:2")
    old["ts"], new["ts"] = "2026-10-20T00:00:00Z", "2026-10-25T00:00:00Z"
    res = pr.compute("vol06", sheet, [old, new], CHAR, None, None, None)
    assert res["fields"]["pending_review"] == 2              # 1:1:1（旧裁、复审）、1:1:3；1:1:2 出单后已裁，7:7:7 不在现文
    assert res["metrics"][0][4] == {"on_sheet": 4, "judged_since_issue": 1, "not_in_text": 1}
