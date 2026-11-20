"""册 yaml 的缺页记录 `gaps:`（2026-11-18 用户定：只按图片页号记缺在哪张图之后）。"""
from __future__ import annotations

import json

import pytest
import yaml

from open_guji_cv.core import book_config as bc
from open_guji_cv.core.book import gap_note, gaps_for_pages, load_book, load_gaps

GAP = {"after_page": 20, "what": "卷九叶九、叶十", "kind": "原书缺", "est_chars": 830,
       "evidence": "图 20 版心叶八、图 21 叶十一相邻"}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    (tmp_path / "books").mkdir()
    (tmp_path / "config").mkdir()
    monkeypatch.delenv(bc.OVERRIDE_ENV, raising=False)
    return tmp_path


def _w(ws, name, doc, sub="books"):
    p = ws / sub / name
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return p


def test_load_book_reads_gaps(ws):
    _w(ws, "v1.yaml", {"id": "v1", "title": "t", "raw_dir": "raw", "gaps": [GAP]})
    assert load_book("v1", ws / "books").gaps == [GAP]


def test_no_gaps_is_empty(ws):
    _w(ws, "v1.yaml", {"id": "v1", "title": "t", "raw_dir": "raw"})
    assert load_book("v1", ws / "books").gaps == []


def test_kind_defaults_and_sorted():
    g = load_gaps([{"after_page": 9, "what": "b"}, {"after_page": 3, "what": "a", "kind": "未拍"}], "v1")
    assert [x["after_page"] for x in g] == [3, 9]
    assert g[1] == {"after_page": 9, "what": "b", "kind": "原书缺"}


@pytest.mark.parametrize("bad", [
    "x",                                               # 不是列表
    [{"after_page": "20", "what": "a"}],               # 页号是字符串
    [{"after_page": -1, "what": "a"}],
    [{"after_page": True, "what": "a"}],
    [{"after_page": 1, "what": " "}],                  # what 必填
    [{"after_page": 1, "what": "a", "kind": "丢了"}],
    [{"after_page": 1, "what": "a", "est_chars": -3}],
    [{"after_page": 1, "what": "a", "leaf": 9}],       # 不认识的键
    [{"after_page": 1, "what": "a"}, {"after_page": 1, "what": "b"}],   # 同一处两条
])
def test_bad_gaps_raise(bad):
    with pytest.raises(bc.BookConfigError):
        load_gaps(bad, "v1")


def test_gaps_forbidden_in_defaults_and_override(ws, monkeypatch):
    p = _w(ws, "v1.yaml", {"id": "v1", "title": "t", "raw_dir": "raw"})
    _w(ws, "book_defaults.yaml", {"gaps": [GAP]}, sub="config")
    with pytest.raises(bc.BookConfigError):
        bc.effective_book_dict(p)
    (ws / "config" / "book_defaults.yaml").unlink()
    monkeypatch.setenv(bc.OVERRIDE_ENV, json.dumps({"gaps": [GAP]}))
    with pytest.raises(bc.BookConfigError):
        bc.effective_book_dict(p)


def test_gaps_for_pages_and_note():
    gaps = load_gaps([GAP, {"after_page": 0, "what": "书衣", "kind": "未拍"}], "v1")
    assert [g["after_page"] for g in gaps_for_pages(gaps, [18, 19, 20])] == [20]   # 缺在章末归本章
    assert gaps_for_pages(gaps, [21, 22]) == []
    assert [g["after_page"] for g in gaps_for_pages(gaps, [1, 2])] == [0]
    assert gap_note(gaps[1]) == "〔原书此处缺卷九叶九、叶十，约 830 字〕"
    assert gap_note(gaps[0]) == "〔此处未拍书衣〕"
