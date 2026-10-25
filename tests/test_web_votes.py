# -*- coding: utf-8 -*-
"""`feedback/web_votes.py`：网站精校投票 → 事件草稿的分流。数据全在测试里造。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from open_guji_cv.feedback.events import EventTarget, make_event
from open_guji_cv.feedback.web_votes import (
    check_cell, cord_boxes, latest_human, latest_votes, load_votes, payload_of, shrink_boxes, triage,
)

BOOK, REV = "sitebk01", "004-r3"


def vote(a, choice, char="", voter="v1", ts=1, **kw):
    return {"v": 1, "book": BOOK, "vol": "004", "a": a, "rev": REV, "choice": choice,
            **({"char": char} if char else {}), "note": "", "voter": voter, "ts": ts, **kw}


def human_ev(key, v="confirm", shape="", ts="2026-10-01T00:00:00Z", kind="confirm", source=None):
    p = {"v": v, **({"shape": shape} if shape else {}), **({"source": source} if source else {})}
    e = make_event("H-test", 1, kind, EventTarget(step="seed_admit", unit="cell", key=key), p)
    return e.model_copy(update={"ts": ts})


def test_payload_mapping():
    assert payload_of("char", "象") == {"v": "confirm", "shape": "象"}
    assert payload_of("cut") == {"v": "seg_defect", "quality": "truncated"}
    assert payload_of("cut", "日") == {"v": "seg_defect", "quality": "truncated", "shape": "日"}
    assert payload_of("jiazhu") == {"v": "seg_defect", "reason": "jiazhu_as_main"}
    assert payload_of("main") == {"v": "seg_defect", "reason": "main_as_jiazhu"}
    assert payload_of("jiazhu", "之") == {"v": "seg_defect", "reason": "jiazhu_as_main", "shape": "之"}
    assert payload_of("none") == {"v": "not_a_char"}
    assert payload_of("damaged") == {"v": "damaged"}
    assert payload_of("damaged", "日") == {"v": "damaged", "guess": "日"}
    assert payload_of("unsure") is None


def test_damaged_vote_is_ready_and_overrides_same_verdict():
    """破损、阙字（2026-10-25）：带不带「最像的字」都能写；和已有的 damaged 人裁一致就跳过。"""
    votes, _ = latest_votes([vote("5:1:1", "damaged"), vote("5:1:2", "damaged", "日"), vote("5:1:3", "damaged")], BOOK, REV)
    human = latest_human([human_ev("vol04:5:1:3", v="damaged")])
    t = triage(votes, "vol04", human)
    assert [(d.a, d.payload) for d in t.ready] == [("5:1:1", {"v": "damaged"}), ("5:1:2", {"v": "damaged", "guess": "日"})]
    assert {a for a, _ in t.skipped} == {"5:1:3"}


def test_latest_votes_dedupes_and_filters():
    raw = [vote("15:8:20", "char", "象", ts=1), vote("15:8:20", "char", "像", ts=2),   # 同格同来源：留新的
           vote("15:8:21", "char", "x", note="【测试】试一下"),                          # 测试票
           {**vote("15:8:22", "char", "y"), "rev": "004-r2"},                           # 别的 rev
           vote("15:8:23", "char", "太長")]                                             # 选字不是单字
    votes, dropped = latest_votes(raw, BOOK, REV)
    assert [(v["a"], v["char"]) for v in votes] == [("15:8:20", "像")]
    assert dropped == {"测试票": 1, "别的书或别的 rev": 1, "选字档没给单字": 1}


def test_load_votes_both_shapes(tmp_path):
    rows = [vote("1:1:1", "none"), vote("1:1:2", "cut")]
    (tmp_path / "a.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({"success": True, "items": rows}), encoding="utf-8")
    assert load_votes(tmp_path / "a.jsonl") == rows == load_votes(tmp_path / "b.json")


def test_triage_routes():
    votes, _ = latest_votes([
        vote("2:1:1", "char", "象"),                                     # 可写
        vote("2:1:2", "none"),                                           # 无字：缺省挂起
        vote("2:1:3", "unsure"),                                         # 只有看不出：跳过
        vote("2:1:4", "char", "甲"), vote("2:1:4", "char", "乙", voter="v2"),   # 意见不一致：挂起
        vote("2:1:5", "char", "丙"),                                     # 与已有人裁一致：跳过
        vote("2:1:6", "char", "丁"),                                     # 推翻已有人裁：挂起
        vote("2:1:7", "char", "戊"),                                     # 只有看图结论（不算人裁）：可写
    ], BOOK, REV)
    human = latest_human([human_ev("vol04:2:1:5", shape="丙"), human_ev("vol04:2:1:6", shape="己"),
                          human_ev("vol04:2:1:7", v="wrong", kind="vision_check", source="vision")])
    t = triage(votes, "vol04", human)
    assert [d.a for d in t.ready] == ["2:1:1", "2:1:7"]
    held = {d.a: d.held for d in t.held}
    assert set(held) == {"2:1:2", "2:1:4", "2:1:6"}
    assert held["2:1:2"].startswith("无字") and held["2:1:4"].startswith("意见不一致") \
        and held["2:1:6"].startswith("要推翻已有人裁")
    assert {a for a, _ in t.skipped} == {"2:1:3", "2:1:5"}
    assert [d.a for d in triage(votes, "vol04", human, include_none=True).ready] == ["2:1:1", "2:1:2", "2:1:7"]
    row = t.ready[0].row("网站精校意见（004-r3）")
    assert row["id"] == "vol04:2:1:1" and row["v"] == "confirm" and row["shape"] == "象"
    assert "v1" in row["source"]


def test_triage_flag_with_char():
    """网站 10-21 起四档能同时带字：切分错了带字照写，无字／看不清带字挂起。"""
    votes, _ = latest_votes([vote("3:1:1", "jiazhu", "之"), vote("3:1:2", "none", "口"), vote("3:1:3", "unsure", "日")],
                            BOOK, REV)
    t = triage(votes, "vol04", {})
    assert [(d.a, d.payload.get("shape")) for d in t.ready] == [("3:1:1", "之")]
    held = {d.a: d.held for d in t.held}
    assert set(held) == {"3:1:2", "3:1:3"} and all(h.startswith("说无字／看不清又给了字") for h in held.values())


def test_latest_human_takes_newest():
    h = latest_human([human_ev("vol04:1:1:1", shape="甲", ts="2026-10-01T00:00:00Z"),
                      human_ev("vol04:1:1:1", shape="乙", ts="2026-10-02T00:00:00Z")])
    assert h["vol04:1:1:1"].payload["shape"] == "乙"


def _cord(width, cells):
    return {"pages": [{"page": 5, "image": {"width": width}, "cells": [{"a": a, "box": b} for a, b in cells]}]}


def _shrink(width, cells):
    """左上原点的 [x, y, w, h] → cell_shrink 的右上原点 bbox_page。"""
    chars = [{"id": f"vol04:{a}", "bbox_page": [width - x - w, y, width - x, y + h]} for a, (x, y, w, h) in cells]
    return {"columns": [{"chars": chars}]}


def test_box_conversion_and_check():
    cells = [("5:1:1", [1800, 500, 110, 120]), ("5:1:2", [1801, 625, 108, 118])]
    old = cord_boxes(_cord(2300, cells))[5][1]
    new = shrink_boxes(_shrink(2300, [(a, [x + 1, y, w, h]) for a, (x, y, w, h) in cells]), 2300)
    assert check_cell("5:1:2", old, new) is None                               # 差 1px：对得上
    moved = shrink_boxes(_shrink(2300, [cells[0], ("5:1:2", [1801, 680, 108, 118])]), 2300)
    assert "格框变了" in check_cell("5:1:1", old, moved)                        # 同列别的格动了也不放行
    fewer = shrink_boxes(_shrink(2300, cells[:1]), 2300)
    assert "现行产物里没有" in check_cell("5:1:2", old, fewer)
    assert "格位变了" in check_cell("5:1:1", old, fewer)


def test_triage_holds_resegmented_cells():
    cells = [("5:1:1", [1800, 500, 110, 120]), ("5:2:1", [1600, 500, 110, 120])]
    old = cord_boxes(_cord(2300, cells))[5][1]
    new = shrink_boxes(_shrink(2300, [cells[0], ("5:2:1", [1600, 560, 110, 120])]), 2300)
    votes, _ = latest_votes([vote("5:1:1", "char", "甲"), vote("5:2:1", "cut")], BOOK, REV)
    t = triage(votes, "vol04", {}, check=lambda a: check_cell(a, old, new))
    assert [d.a for d in t.ready] == ["5:1:1"]
    assert t.held[0].a == "5:2:1" and t.held[0].held.startswith("格位对不上")


def test_draft_with_pack_uses_issue_products(tmp_path, monkeypatch):
    """`--pack rev-…`：取回出单版产物包当产物根（取过就复用），不要 --cord；meta 记下产物根给 write 用。"""
    import argparse

    from open_guji_cv import cli_cellvotes as C
    from open_guji_cv.datastore import packs as PK
    ws = tmp_path / "ws"
    (ws / "feedback" / "events").mkdir(parents=True)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    monkeypatch.delenv("GUJI_PRODUCTS_DIR", raising=False)
    fetched = []

    def fake_fetch(book, dest_root, label=None, force=False, src=None):
        fetched.append(label)
        (Path(dest_root) / book / "cell_shrink").mkdir(parents=True)
        return {"name": f"x/{label}", "dest": str(Path(dest_root) / book), "files": 1}

    monkeypatch.setattr(PK, "fetch_products", fake_fetch)
    votes = tmp_path / "votes.jsonl"
    votes.write_text(json.dumps(vote("1:1:1", "char", "甲")) + "\n", encoding="utf-8")
    out = tmp_path / "draft"
    args = argparse.Namespace(book="vol04", site_book=BOOK, rev=REV, cord=None, no_box_check=False, tol=8.0,
                              include_none=False, from_file=str(votes), from_kv=False, token_env="X",
                              source="测试", out=str(out), pack="rev-004-r3")
    C.cmd_draft(args)
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["pack"] == "rev-004-r3" and meta["products_root"].endswith("_packs/rev-004-r3")
    assert os.environ["GUJI_PRODUCTS_DIR"] == meta["products_root"] and meta["ready"] == 1
    C.cmd_draft(args)
    assert fetched == ["rev-004-r3"]                                     # 第二次复用，不再取


def test_overturn_on_recheck_sheet_and_recheck_rows():
    """复审单上写明了旧裁（prior.id）的格，投了不同的字＝有意推翻：照写并记 overrides；
    旧裁不是单上那条（出单后又来了新裁）照旧挂起；挂起里能回网站的写成复审清单。"""
    from open_guji_cv.feedback.web_votes import recheck_rows
    old = human_ev("vol04:2:1:6", shape="己")
    newer = human_ev("vol04:2:1:8", shape="庚", ts="2026-10-03T00:00:00Z")
    votes, _ = latest_votes([
        vote("2:1:6", "char", "丁"),                                     # 单上 prior 就是 old → 推翻
        vote("2:1:8", "char", "辛"),                                     # 单上 prior 是更早那条 → 挂起
        vote("2:1:4", "char", "甲"), vote("2:1:4", "char", "乙", voter="v2"),
        vote("3:1:2", "none", "口"),
        vote("2:1:2", "none"),                                           # 无字：挂起但不回网站
    ], BOOK, REV)
    human = latest_human([old, newer])
    t = triage(votes, "vol04", human, sheet_prior={"2:1:6": old.id, "2:1:8": "older-event"})
    ready = {d.a: d.payload for d in t.ready}
    assert ready == {"2:1:6": {"v": "confirm", "shape": "丁", "overrides": old.id}}
    kinds = {d.a: d.kind for d in t.held}
    assert kinds == {"2:1:8": "overturn", "2:1:4": "disagree", "3:1:2": "guess", "2:1:2": "none"}
    rows = {r[0]: r for r in recheck_rows(t)}
    assert set(rows) == {"2:1:8", "2:1:4", "3:1:2"}
    assert rows["2:1:8"][2:4] == (newer.id, "庚") and "「辛」" in rows["2:1:8"][1]
    assert "「甲」" in rows["2:1:4"][1] and "「乙」" in rows["2:1:4"][1]
    assert "没有字「口」" in rows["3:1:2"][1]
