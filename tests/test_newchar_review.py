# -*- coding: utf-8 -*-
"""scripts/build_newchar_review.py：挑新字格、卡片排序、裁决 → 字（造数据，不碰真书）。"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from collections import Counter
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_newchar_review", Path(__file__).resolve().parents[1] / "scripts" / "build_newchar_review.py")
nc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(nc)


def _wr(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _seed(root: Path) -> None:
    def ch(slot, char, admit, doubts=()):
        return {"id": f"b1:1:1:{slot}", "slot": slot, "sub": None, "char": char, "admit": admit,
                "doubts": list(doubts), "channel": None, "evidence": {}, "provenance": ""}
    _wr(root / "b1/seed_admit/p0001.json", {"seed_admit": {"page": 1, "columns": [{"col": 1, "chars": [
        ch(1, "甲", True), ch(2, "庫", False), ch(3, "乙", False, ["ctx_guard_ref"]),
        ch(4, "丙", False), ch(5, "丁", False)]}]}})
    al = [{"id": f"b1:1:1:{s}", "col": 1, "slot": s, "sub": None, "align_char": c, "align_op": "equal", "ref_run": 3}
          for s, c in [(1, "甲"), (2, "㚲"), (3, "乙"), (4, "有"), (5, "")]]
    _wr(root / "b1/align_ref/p0001.json", {"align_ref": {"chars": al}})
    _wr(root / "b1/glyph_match/p0001.json", {"glyph_match": {"columns": [{"chars": [
        {"id": "b1:1:1:2", "candidates": [["庫", 0.9], ["㡹", 0.8]], "cov": 0.9}]}]}})
    _wr(root / "b1/rare_candidates/p0001.json", {"rare_candidates": {"columns": [{"chars": [
        {"id": "b1:1:1:2", "candidates": [{"char": "㚲", "score": 1}, {"char": "姑", "score": 1},
                                          {"char": "姑", "score": 1}, {"char": "姞", "score": 1}]}]}]}})


def test_lib_counts_ignores_stale(tmp_path):
    db = tmp_path / "g.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE instances (label TEXT, label_status TEXT)")
    c.executemany("INSERT INTO instances VALUES (?,?)",
                  [("有", "human"), ("有", "align"), ("乙", "human_stale_20260917"), ("", "human")])
    c.commit(); c.close()
    assert nc.lib_counts(db) == Counter({"有": 2})


def test_collect_picks_only_review_cells_whose_ref_char_is_absent(tmp_path):
    _seed(tmp_path)
    st = Counter()
    cards = nc.collect_book("b1", tmp_path, Counter({"有": 5, "甲": 9}), 1, set(), st)
    assert {c["id"] for c in cards} == {"b1:1:1:2", "b1:1:1:3"}   # 丙对位出「有」在库里 → 不是新字；丁无整理本字
    assert st["no_ref"] == 1 and st["ref_in_lib"] == 1 and st["review"] == 4
    c2 = next(c for c in cards if c["id"] == "b1:1:1:2")
    assert (c2["ref"], c2["lib_top"], c2["r5"], c2["warn"]) == ("㚲", "庫", ["㚲", "姑", "姞"], False)
    assert c2["ctx"] == "甲【㚲】乙有□"
    assert next(c for c in cards if c["id"] == "b1:1:1:3")["warn"] is True
    # 已有人裁的格不再出卡
    st = Counter()
    assert [c["id"] for c in nc.collect_book("b1", tmp_path, Counter({"有": 5}), 1, {"b1:1:1:2"}, st)] == ["b1:1:1:3"]
    # 阈值抬高，库里只有 5 例的「有」也算不足
    assert len(nc.collect_book("b1", tmp_path, Counter({"有": 5}), 6, set(), Counter())) == 3


def test_order_and_verdict_chars():
    cards = [{"id": "b:2:1:1", "ref": "乙", "warn": False}, {"id": "b:1:1:1", "ref": "甲", "warn": False},
             {"id": "b:1:1:9", "ref": "乙", "warn": False}, {"id": "b:3:1:1", "ref": "丙", "warn": True}]
    assert [c["id"] for c in nc.order_cards(cards)] == ["b:3:1:1", "b:1:1:9", "b:2:1:1", "b:1:1:1"]
    card = {"ref": "㚲"}
    assert nc.verdict_to_char(card, "ref") == "㚲"
    assert nc.verdict_to_char(card, "pick:姑") == "姑"
    assert nc.verdict_to_char(card, "pick:") is None
    assert all(nc.verdict_to_char(card, v) is None for v in ("seg", "unclear", "other"))
