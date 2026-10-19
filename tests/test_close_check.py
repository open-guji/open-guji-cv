# -*- coding: utf-8 -*-
"""`guji close-check` 的离线各项（overview#413 C2）：只用 tmp 里现造的文件，不碰工作区。"""
from __future__ import annotations

import json

import pytest

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


def test_store_committed_requires_migration(tmp_path):
    (tmp_path / "workspace.yaml").write_text("id: x\n", encoding="utf-8")
    r = CC._store_committed(tmp_path)
    assert r["status"] == CC.FAIL and "db migrate" in r["detail"]


def test_report_prints(capsys):
    res = {"book": "vol09", "workspace": "/ws", "pages": 3, "machine_ok": False,
           "counts": {"pass": 1, "fail": 1, "error": 0, "manual": 6, "skip": 0},
           "items": [CC._item("1a", "产物新鲜", CC.PASS, "全部新鲜"), CC._item("2", "待审清零", CC.FAIL, "待审 3 格")]}
    CC.print_report(res)
    out = capsys.readouterr().out
    assert "✗   2 待审清零" in out and "机器项未通过" in out


def test_queue_errors_when_glyph_store_missing(tmp_path):
    """没有字形库的工作区上待审数不可信：_queue 必须报错，不能给「待审 0 ✓」（GUJI-364）。"""
    assert CC._glyph_store_missing(tmp_path) is not None
    with pytest.raises(RuntimeError, match="缺字形库"):
        CC._queue("vol01", None, tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "glyph.db").write_text("")
    assert CC._glyph_store_missing(tmp_path) is None


def test_empty_glyph_store_dir_counts_as_missing(tmp_path):
    """空 glyph_store 目录不算有库；2b 收尾闸同样报错。"""
    (tmp_path / "output" / "glyph_store").mkdir(parents=True)
    assert CC._glyph_store_missing(tmp_path)
    with pytest.raises(RuntimeError):
        CC._closure("vol01", [], None, tmp_path)
    (tmp_path / "output" / "glyph_store" / "glyphs.jsonl").write_text("")
    assert CC._glyph_store_missing(tmp_path) is None


# ── 粗校档／终校档（Maren 10-17 定，GUJI-555）：第 2 项待审清零 ────────────────
def _fake_cards(monkeypatch, n: int, nv: int = 0):
    import open_guji_cv.review.cards as RC
    monkeypatch.setattr(RC, "cards", lambda *a, **k: {
        "class_counts": {"near_form": n} if n else {}, "doubt_counts": {"vision_flag": nv} if nv else {}})
    monkeypatch.setattr(CC, "_glyph_store_missing", lambda ws: None)


def test_final_tier_fails_when_pending(monkeypatch, tmp_path):
    _fake_cards(monkeypatch, 466)
    it = CC._queue("b", None, tmp_path)               # 缺省＝终校档
    assert it["status"] == CC.FAIL and "466" in it["detail"]


def test_rough_tier_reports_but_does_not_count_pending(monkeypatch, tmp_path):
    _fake_cards(monkeypatch, 466, nv=3)
    it = CC._queue("b", None, tmp_path, tier="rough")
    assert it["status"] == CC.PASS
    assert "466" in it["detail"] and "粗校档不计" in it["detail"] and "vision_flag" in it["detail"]


def test_both_tiers_pass_when_nothing_pending(monkeypatch, tmp_path):
    _fake_cards(monkeypatch, 0)
    assert CC._queue("b", None, tmp_path)["status"] == CC.PASS
    assert CC._queue("b", None, tmp_path, tier="rough")["status"] == CC.PASS


def test_rough_tier_does_not_hide_a_missing_glyph_store(monkeypatch, tmp_path):
    """粗校档只放过『待审数』，不放过『待审数不可信』（缺字形库照样出错，不能假绿）。"""
    import open_guji_cv.review.cards as RC
    monkeypatch.setattr(RC, "cards", lambda *a, **k: {"class_counts": {}})
    monkeypatch.setattr(CC, "_glyph_store_missing", lambda ws: "缺库")
    with pytest.raises(RuntimeError):
        CC._queue("b", None, tmp_path, tier="rough")


def test_cli_tier_defaults_to_final():
    import argparse
    from open_guji_cv import cli_v2
    root = argparse.ArgumentParser()
    cli_v2.register_subcommands(root.add_subparsers(dest="command"))
    assert root.parse_args(["close-check", "b", "-w", "/x"]).tier == "final"
    assert root.parse_args(["close-check", "b", "-w", "/x", "--tier", "rough"]).tier == "rough"


def test_queue_skips_cells_on_recut_list(monkeypatch, tmp_path):
    """重切清单上的格不算待审（D 10-19：book-text 手拼的列，cv 的格 id 对不上，落不了格事件）。"""
    import open_guji_cv.review.cards as RC
    from open_guji_cv.ops import release_gates as RG
    cs = [{"page": 10, "col": 7, "slot": 3, "sub": "", "cls": "near_form", "doubts": []},
          {"page": 89, "col": 2, "slot": 1, "sub": "a", "cls": "near_form", "doubts": ["vision_flag"]},
          {"page": 90, "col": 1, "slot": 4, "sub": "", "cls": "no_ref", "doubts": []},
          {"page": 12, "col": 1, "slot": 1, "sub": "", "cls": "near_form", "doubts": []}]

    def fake(*a, **k):
        if k.get("limit") == 1:
            return {"class_counts": {"near_form": 3, "no_ref": 1}, "doubt_counts": {"vision_flag": 1}}
        return {"cards": cs, "truncated": False}
    monkeypatch.setattr(RC, "cards", fake)
    monkeypatch.setattr(CC, "_glyph_store_missing", lambda ws: None)
    monkeypatch.setattr(RG, "lists_dir", lambda: tmp_path / "lists")
    assert "4 格" in CC._queue("b", None, tmp_path)["detail"]       # 没有重切清单：照旧
    RG.recut_path("b", tmp_path / "lists").parent.mkdir(parents=True)
    RG.recut_path("b", tmp_path / "lists").write_text("位置\t原因\n10:7\t手拼\n89\t职名页\n90:1:4\tx\n", encoding="utf-8")
    it = CC._queue("b", None, tmp_path)
    assert it["status"] == CC.FAIL and "待审 1 格" in it["detail"] and "3 格在重切清单上" in it["detail"]
    assert it["data"] == {"near_form": 1} and "vision_flag" not in it["detail"]
    RG.recut_path("b", tmp_path / "lists").write_text("位置\t原因\n10:7\t手拼\n89\t职名页\n90:1:4\tx\n12\ty\n", encoding="utf-8")
    assert CC._queue("b", None, tmp_path)["status"] == CC.PASS
