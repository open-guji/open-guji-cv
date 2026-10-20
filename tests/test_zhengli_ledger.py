# -*- coding: utf-8 -*-
"""scripts/zhengli/ledger.py：统一人审率口径（GUJI-667 D6.1）。数据全在 tmp_path 里自造。"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

LEDGER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "zhengli" / "ledger.py"
spec = importlib.util.spec_from_file_location("ledger_under_test", LEDGER_PATH)
ledger = importlib.util.module_from_spec(spec)
sys.modules["ledger_under_test"] = ledger
spec.loader.exec_module(ledger)


def _cells(anchors):
    return [{"id": f"g{i}", "a": a, "o": i, "c": "字"} for i, a in enumerate(anchors)]


def make_pages_json(p6_type: str | None = "roster") -> dict:
    """三页：p5 正文（第 1 列是卷端题 3 格 + 1 格正文，第 2 列 5 格；一格非字、一格留白），
    p6 页型由 pages.json 自带（缺省职名＝非正文），p7 页型靠调用方给（含夹注 a/b）。"""
    p6_page = {"index": 6}
    if p6_type:
        p6_page["page_type"] = p6_type
    return {"schema": "guji-pages/0.1", "pages": [
        {"page": {"index": 5}, "cells": _cells(["5:1:1", "5:1:2", "5:1:3", "5:1:4",
                                                "5:2:1", "5:2:2", "5:2:3", "5:2:4", "5:2:5"]),
         "marks": [{"id": "m1", "kind": "excluded", "col": "c2", "slot": 6, "cv_id": "vol04:5:2:6"},
                   {"id": "m2", "kind": "blank", "col": "c3", "slot": 1}]},
        {"page": p6_page, "cells": _cells(["6:1:1", "6:1:2", "6:1:3"]), "marks": []},
        {"page": {"index": 7}, "cells": _cells(["7:1:1", "7:1:2a", "7:1:2b"]), "marks": []},
    ]}


def make_pending() -> dict:
    return {"rev": "vol04-r1", "cv_version": None, "cv_commit": "abcd1234", "cells": [
        {"cell": "5:1:2", "review": "pending", "why": ["near_form"], "cls": "near_form"},   # 标题槽
        {"cell": "5:2:1", "review": "pending", "why": ["near_form"], "cls": "near_form"},
        {"cell": "5:2:1", "review": "pending", "why": ["near_form"], "cls": "near_form"},   # 重复，去重
        {"cell": "5:2:3", "review": "human", "why": ["lib_unsure", "ctx_margin"], "cls": "other"},
        {"cell": "5:2:6", "review": "pending", "why": ["occluded"], "cls": "occluded"},     # 非字格
        {"cell": "6:1:1", "review": "pending", "why": ["lib_miss"], "cls": "lib_miss"},     # 非正文页
        {"cell": "7:1:2a", "review": "pending"},                                            # 没写 why/cls
        {"cell": "9:1:1", "review": "pending", "cls": "other"},                             # pages.json 里没有
    ]}


PUNCT = {"punctuations": [
    {"kind": "heading", "pos": "before", "mark": "#", "anchor": "5:1:1", "char_offset": 0},
    {"kind": "break", "pos": "after", "mark": "\n\n", "anchor": "5:1:3", "char_offset": 2},
    {"kind": "point", "pos": "after", "mark": "。", "anchor": "5:2:2", "char_offset": 5},
    {"kind": "break", "pos": "after", "mark": "\n\n", "anchor": "5:2:5", "char_offset": 8},
]}


class FakeRecut:
    def __init__(self, cols):
        self.cols = set(cols)

    def covers_cell(self, a):
        pg, col, *_ = a.split(":")
        return (int(pg), int(col)) in self.cols


def test_body_title_nonchar_exclusions():
    r = ledger.review_rate(make_pages_json(), make_pending(), page_types={7: "body"}, punct=PUNCT)
    # 正文字格：p5 9 格 − 标题 3 格 + p7 3 格 = 9；p6 职名不计
    assert r["total_cells"] == 9
    assert r["title_slots_excluded"] == 3 and r["title_review"] == 1 and r["title_unresolved"] == 0
    # 分子：5:2:1、5:2:3、7:1:2a（标题槽、非字格、非正文、找不到的都不算）
    assert r["review_cells"] == 3
    assert r["rate"] == round(3 / 9, 6)
    assert r["nonbody_review"] == 1 and r["nonbody_cells"] == 3
    assert r["nonchar_excluded"] == 2 and r["nonchar_review"] == 1
    assert r["unmatched_review"] == 1 and r["unmatched_sample"] == ["9:1:1"]
    assert r["pending_cells"] == 7
    assert (r["body_pages"], r["nonbody_pages"], r["pages_untyped"]) == (2, 1, 1)   # p5 没页型


def test_without_punct_title_slots_stay_in():
    r = ledger.review_rate(make_pages_json(), make_pending(), page_types={7: "body"})
    assert r["title_slots_excluded"] == 0
    assert r["total_cells"] == 12 and r["review_cells"] == 4


def test_page_type_sources_and_defaults():
    # pages.json 自带的页型优先于调用方给的；都没有的页按 body 计、记 untyped
    r = ledger.review_rate(make_pages_json(), make_pending(), page_types={6: "body"})
    assert r["nonbody_review"] == 1 and r["pages_untyped"] == 2
    # 调用方说 p7 是目录 → 非正文
    r = ledger.review_rate(make_pages_json(p6_type=None), make_pending(), page_types={7: "toc"})
    assert r["total_cells"] == 12 and r["review_cells"] == 4 and r["nonbody_review"] == 1
    # blank 是 body 的子类
    r = ledger.review_rate(make_pages_json(p6_type="blank"), make_pending())
    assert r["nonbody_review"] == 0 and r["total_cells"] == 15


def test_all_pages_mode_includes_nonbody():
    r = ledger.review_rate(make_pages_json(), make_pending(), body_only=False, punct=PUNCT)
    assert r["total_cells"] == 12 and r["review_cells"] == 4 and r["nonbody_review"] == 1


def test_reasons_and_status_counts():
    r = ledger.review_rate(make_pages_json(), make_pending(), page_types={7: "body"}, punct=PUNCT)
    assert r["reasons"]["cls"] == {"near_form": 1, "none": 1, "other": 1}
    assert r["reasons"]["why"] == {"ctx_margin": 1, "lib_unsure": 1, "near_form": 1, "none": 1}
    assert r["review_status"] == {"pending": 2, "human": 1}


def test_recut_reported_not_subtracted():
    r = ledger.review_rate(make_pages_json(), make_pending(), page_types={7: "body"}, punct=PUNCT,
                           recut=FakeRecut({(5, 2)}))
    assert r["recut_cells"] == 5 and r["review_on_recut"] == 2
    assert r["review_cells"] == 3 and r["total_cells"] == 9


def test_heading_without_break_is_unresolved():
    punct = {"punctuations": [{"kind": "heading", "anchor": "5:1:1"},
                              {"kind": "heading", "anchor": "5:2:1"},
                              {"kind": "break", "anchor": "5:2:2"},
                              {"kind": "heading", "anchor": "99:1:1"}]}
    order = [c["a"] for p in make_pages_json()["pages"] for c in p["cells"]]
    titles, bad = ledger.title_cells(order, punct)
    assert titles == {"5:2:1", "5:2:2"} and bad == 2


# ---------------------------------------------------------------- CLI
def _write_inputs(tmp_path) -> dict:
    ws = tmp_path / "ws"
    ws.mkdir()
    d = tmp_path / "in"
    d.mkdir()
    pj, pd = d / "004.pages.json", d / "004.pending.json"
    pj.write_text(json.dumps(make_pages_json(p6_type=None), ensure_ascii=False), encoding="utf-8")
    pd.write_text(json.dumps(make_pending(), ensure_ascii=False), encoding="utf-8")
    recut = d / "vol04-重切清单.tsv"
    recut.write_text("位置\t原因\n5:2\t并格\n# 注释\nxx\t写坏\n", encoding="utf-8")
    punct = d / "004.punct.json"
    punct.write_text(json.dumps(PUNCT), encoding="utf-8")
    # p6 的页型从产物（闸1）取；p7 没有任何来源 → 按 body
    gate = ws / "products" / "vol04" / "border_detect_gate"
    gate.mkdir(parents=True)
    (gate / "p0006.json").write_text(json.dumps(
        {"border_detect_gate_manifest": {"page": 6, "page_type": "roster"}}), encoding="utf-8")
    return {"ws": ws, "pj": pj, "pd": pd, "recut": recut, "punct": punct}


def _argv(f, *extra):
    return ["--ws", str(f["ws"]), "--book", "vol04", "--pages-json", str(f["pj"]),
            "--pending", str(f["pd"]), "--recut", str(f["recut"]), "--punct", str(f["punct"]), *extra]


def test_cli_appends_jsonl_and_is_reproducible(tmp_path, monkeypatch):
    f = _write_inputs(tmp_path)
    monkeypatch.setenv("GUJI_WORKSPACE", str(f["ws"]))   # main 会改它，交给 monkeypatch 还原
    out = tmp_path / "ledger.jsonl"
    assert ledger.main(_argv(f, "--out", str(out))) == 0
    assert ledger.main(_argv(f, "--out", str(out))) == 0
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    a, b = rows
    assert a.pop("ts") and b.pop("ts")
    assert a == b                                    # 同一输入重算相同（除 ts）
    for k in ("book", "cv_version", "cv_commit", "corpus", "glyph_pin", "total_cells", "review_cells",
              "rate", "nonbody_review", "recut_cells", "reasons"):
        assert k in a
    assert a["book"] == "vol04" and a["cv_version"] is None and a["pins_error"]
    assert (a["total_cells"], a["review_cells"], a["nonbody_review"]) == (9, 3, 1)
    assert a["recut_cells"] == 5 and a["recut_rows"] == 1 and a["recut_bad"] == ["xx"]
    assert a["title_source"] == "punct"
    assert a["page_type_source"] == {"border_detect_gate": 1, "default_body": 2}
    assert a["pending_rev"] == "vol04-r1" and a["inputs"]["pages_json"]


def test_cli_default_out_in_data_dir(tmp_path, monkeypatch):
    f = _write_inputs(tmp_path)
    monkeypatch.setenv("GUJI_WORKSPACE", str(f["ws"]))
    assert ledger.main(_argv(f)) == 0
    out = f["ws"] / "feedback" / "lists" / "ledger" / "vol04.jsonl"
    assert out.is_file() and len(out.read_text(encoding="utf-8").splitlines()) == 1


def test_build_row_ts_is_los_angeles(tmp_path, monkeypatch):
    f = _write_inputs(tmp_path)
    monkeypatch.setenv("GUJI_WORKSPACE", str(f["ws"]))
    now = datetime(2026, 10, 20, 9, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
    row = ledger.build_row("vol04", f["pj"], f["pd"], f["recut"], None, now=now)
    assert row["ts"] == "2026-10-20T09:30:00-07:00"
    assert row["title_source"] == "none" and row["total_cells"] == 12


def test_cli_missing_pending_fails(tmp_path, monkeypatch):
    f = _write_inputs(tmp_path)
    monkeypatch.setenv("GUJI_WORKSPACE", str(f["ws"]))
    argv = ["--ws", str(f["ws"]), "--book", "vol04", "--pages-json", str(f["pj"]), "--out", str(tmp_path / "o")]
    with pytest.raises(SystemExit):
        ledger.main(argv)
