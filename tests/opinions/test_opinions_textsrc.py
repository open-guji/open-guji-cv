# -*- coding: utf-8 -*-
"""意见池 A3：text_versions 解析（book-text CHANGES）与 locate。数据自造（booktext_fixture）。"""
from __future__ import annotations

from booktext_fixture import BOOK, CHANGES, CHANGES_101, make

from open_guji_cv.opinions.schema import Opinion, make_id
from open_guji_cv.opinions.textsrc import BookText, locate, parse_changes


def test_parse_changes_rows():
    tv = parse_changes(CHANGES, BOOK)
    assert sorted(tv) == ["002", "003"]
    assert [r["text_version"] for r in tv["002"]] == ["1.0.0", "1.0.1", "1.0.2"]      # 「（不变）」、实体线、别的书不算
    first, manual, rev = tv["002"]
    assert first["kind"] == "cv_export" and first["cv_version"] == "0.2.0" and first["cv_commit"] == "4a9388ac"
    assert first["snapshot"] == "snap/bkxyz/vol02/20261007T0100" and first["rev"] == "002-r1" and first["pr"] == "#22"
    assert manual["kind"] == "manual" and manual["from"] == "1.0.0" and "|含列末" in manual["note"]
    assert manual["rev"] is None and manual["snapshot"] is None          # 散文里没有的留空
    assert rev["kind"] == "revise" and rev["opinions"] == ["op_span_0123456789"]
    assert tv["003"][0]["cv_version"] == "rc/v0.4.6" and tv["003"][0]["kind"] == "cv_export"


def _op(**kw):
    d = dict(id=make_id("span", "k"), book=BOOK, vol="002", channel="span", raw_id="r", ts="2026-10-20T00:00:00Z",
             target={"start": "3:1:3", "end": "3:1:3", "text_version": "1.0.1", "check": "卷"}, category="missing",
             proposal={"text": "卷一"})
    d.update(kw)
    return Opinion(**d)


def test_locate_current_and_inherited_fields(tmp_path):
    make(tmp_path, changes=CHANGES_101)
    bt = BookText(BOOK, tmp_path)
    tv = parse_changes(bt.changes(), BOOK)
    r = locate(_op(), tv, bt)
    assert r["cell"] == "3:1:3" and r["current_version"] == "1.0.1" and r["text_version"] == "1.0.1"
    assert r["current_text"] == "卷" and r["drift"] is None and r["since"] == []
    # 手改版本沿用它基于的那次导出的 rev、快照
    assert r["rev"] == "002-r1" and r["snapshot"] == "snap/bkxyz/vol02/20261007T0100"
    assert r["cord_producer"]["rev"] == "abc1234"


def test_locate_drift_and_already(tmp_path):
    make(tmp_path)
    bt = BookText(BOOK, tmp_path)
    tv = parse_changes(bt.changes(), BOOK)
    r = locate(_op(target={"start": "3:1:3", "end": "3:1:3", "text_version": "1.0.0", "check": "眷"}), tv, bt)
    assert r["since"] == ["1.0.1", "1.0.2"] and "眷" in r["drift"]
    r = locate(_op(target={"start": "3:1:2", "end": "3:1:2", "text_version": "1.0.0", "check": "宀"},
                   proposal={"text": "定"}), tv, bt)
    assert r["already"] and "已改" in r["drift"]
    r = locate(_op(target={"start": "3:1:1", "end": "3:1:1", "text_version": "9.9.9"}), tv, bt)
    assert any("9.9.9" in m for m in r["missing"])
    # 精校票按 rev 定版本
    r = locate(_op(target={"start": "3:1:1", "end": "3:1:1", "rev": "002-r1"}), tv, bt)
    assert r["asked_at"] == "1.0.0" and r["rev"] == "002-r1"
