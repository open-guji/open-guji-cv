# -*- coding: utf-8 -*-
"""`guji close-check` 的离线各项（overview#413 C2）：只用 tmp 里现造的文件，不碰工作区。"""
from __future__ import annotations

import json
import subprocess

from open_guji_cv.ops import close_check as CC


def _write_export(d, chars: str, offsets: list[int]):
    (d / "009.lines.md").write_text("<!-- p1 -->\n" + chars + "\n", encoding="utf-8")
    pages = {"schema": "guji-pages/0.1", "pages": [{"cells": [{"a": f"1:1:{i + 1}", "o": o, "c": "x"}
                                                             for i, o in enumerate(offsets)]}]}
    (d / "009.pages.json").write_text(json.dumps(pages), encoding="utf-8")


def test_export_consistent(tmp_path):
    _write_export(tmp_path, "甲乙丙", [0, 1, 2])
    items = {it["no"]: it for it in CC._export(tmp_path, None)}
    assert items["10"]["status"] == CC.PASS and items["10"]["data"]["chars"] == 3
    assert items["11"]["status"] == CC.PASS


def test_export_missing_box_fails(tmp_path):
    _write_export(tmp_path, "甲乙丙", [0, 2])
    items = {it["no"]: it for it in CC._export(tmp_path, None)}
    assert items["11"]["status"] == CC.FAIL
    assert items["11"]["data"]["missing"] == [1]


def test_export_extra_box_fails(tmp_path):
    _write_export(tmp_path, "甲乙", [0, 1, 5])
    items = {it["no"]: it for it in CC._export(tmp_path, None)}
    assert items["11"]["status"] == CC.FAIL and items["11"]["data"]["extra"] == [5]


def test_export_needs_exactly_one_lines(tmp_path):
    assert CC._export(tmp_path, None)[0]["status"] == CC.FAIL


def test_notes_and_step9(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    res = {it["no"]: it["status"] for it in CC._notes(notes)}
    assert res == {"7": CC.FAIL, "13": CC.FAIL}
    (notes / "避諱改字表-v1.md").write_text("x", encoding="utf-8")
    (notes / "收尾记录.md").write_text("x", encoding="utf-8")
    assert all(it["status"] == CC.PASS for it in CC._notes(notes))

    rep = tmp_path / "reports"
    assert CC._step9(rep, "vol09")["status"] == CC.FAIL
    (rep / "vol09").mkdir(parents=True)
    (rep / "vol09" / "vol09.md").write_text("x", encoding="utf-8")
    (rep / "vol09" / "collation_20261006.html").write_text("x", encoding="utf-8")
    assert CC._step9(rep, "vol09")["status"] == CC.PASS


def test_store_committed(tmp_path):
    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.email", "t@t"); git("config", "user.name", "t")
    (tmp_path / "feedback").mkdir()
    (tmp_path / "feedback" / "e.jsonl").write_text("{}\n", encoding="utf-8")
    assert CC._store_committed(tmp_path)["status"] == CC.FAIL
    git("add", "-A"); git("commit", "-qm", "x")
    assert CC._store_committed(tmp_path)["status"] == CC.PASS


def test_report_prints(capsys):
    res = {"book": "vol09", "workspace": "/ws", "pages": 3, "machine_ok": False,
           "counts": {"pass": 1, "fail": 1, "error": 0, "manual": 6, "skip": 0},
           "items": [CC._item("1a", "产物新鲜", CC.PASS, "全部新鲜"), CC._item("2", "待审清零", CC.FAIL, "待审 3 格")]}
    CC.print_report(res)
    out = capsys.readouterr().out
    assert "✗   2 待审清零" in out and "机器项未通过" in out
