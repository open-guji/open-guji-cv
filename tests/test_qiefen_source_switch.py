# -*- coding: utf-8 -*-
"""换图源的两处支撑（doc/design/殿本换图源-siku-qiefen-v2.md §三、§四）：

- 预发版页表（status=staged）不被「取最新」拿到，只能按 rev 取；册 yaml 的 `source_rev` 读得进来。
- 迁移来的人裁（锚带 `migrated_from`）不重复进字形库。
"""
from __future__ import annotations

import json

import pytest

from open_guji_cv.datastore import sources as S
from open_guji_cv.feedback.consumers import glyphdb_admit
from open_guji_cv.feedback.events import EventTarget, make_event


class _FakeSrc:
    def __init__(self, tables: dict[int, dict]):
        self.objs = {S.table_key("96mid1ogzk", "11", r): json.dumps(t).encode() for r, t in tables.items()}

    def _call(self, method, path, query=None, raw=False):
        if path == "/v1/packs":
            return {"packs": [{"key": k} for k in self.objs if k.startswith(query["prefix"])]}
        import urllib.parse
        return self.objs[urllib.parse.unquote(path[len("/v1/packs/"):])]


def _t(rev, status="final"):
    return {"rev": rev, "status": status, "pages": []}


def test_latest_skips_staged_table():
    src = _FakeSrc({1: _t(1), 2: _t(2), 3: _t(3, "staged")})
    assert S.read_table(src, "96mid1ogzk", "11")["rev"] == 2
    assert S.read_table(src, "96mid1ogzk", "11", 3)["status"] == "staged"


def test_only_staged_tables_need_explicit_rev():
    src = _FakeSrc({1: _t(1, "staged")})
    with pytest.raises(FileNotFoundError, match="source_rev"):
        S.read_table(src, "96mid1ogzk", "11")


def test_book_yaml_source_rev(tmp_path):
    from open_guji_cv.core.book import load_book
    (tmp_path / "q.yaml").write_text("id: q\ntitle: q\nraw_dir: /tmp/q\nsource_rev: 3\n", encoding="utf-8")
    (tmp_path / "p.yaml").write_text("id: p\ntitle: p\nraw_dir: /tmp/p\n", encoding="utf-8")
    assert load_book("q", tmp_path).source_rev == 3
    assert load_book("p", tmp_path).source_rev is None


def _ev(seq, migrated: bool):
    anchor = {"bbox": [0, 0, 1, 1], "space": "raw_page_px@top-right"}
    if migrated:
        anchor["migrated_from"] = {"book": "vol11", "page": 5, "source": "siku-qiefen-v2"}
    return (make_event("t", seq, "confirm",
                       EventTarget(step="seed_admit", unit="cell", key=f"vol11:5:1:{seq}",
                                   book="vol11", page=5, col=1, slot=seq, anchor=anchor),
                       {"v": "confirm", "shape": "古"}), None)


def test_migrated_events_not_admitted_twice():
    res = glyphdb_admit([_ev(1, True), _ev(2, True)], dry_run=True)
    assert res.added == 0
    res = glyphdb_admit([_ev(1, True), _ev(2, False)], dry_run=True)
    assert res.added == 1
