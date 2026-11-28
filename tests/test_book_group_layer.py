"""配置组层（2026-11-28，CV0）：代码缺省 < 组 < 书（基础配置）< 册 < 运行覆盖。见 core/book_config.py 模块头。"""
from __future__ import annotations

import json

import pytest
import yaml

from open_guji_cv.core import book_config as bc

VOL = {"id": "v1", "title": "t", "raw_dir": "raw"}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    (tmp_path / "books").mkdir()
    (tmp_path / "config").mkdir()
    monkeypatch.delenv(bc.OVERRIDE_ENV, raising=False)
    monkeypatch.delenv("GUJI_DATA_BRANCH", raising=False)
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "data_home"))
    monkeypatch.delenv("GUJI_WORKSPACE", raising=False)
    return tmp_path


def _w(p, doc):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return p


def _group(name, ver, doc):
    return _w(bc.group_config_path(name, ver), doc)


def test_group_sits_between_code_and_book(ws):
    _group("wyg", 1, {"meta": {"title": "文渊阁写本"}, "expected_cols": 8, "chars_per_line": 21,
                      "params": {"align_ref": {"coord_dp": True, "coord_relaxed": True}}})
    _w(ws / "config" / "book_defaults.yaml", {"groups": {"config": "wyg@1", "glyph": ["wyg"]}, "chars_per_line": 22,
                                               "params": {"align_ref": {"coord_relaxed": False}}})
    p = _w(ws / "books" / "v1.yaml", VOL)
    d = bc.effective_book_dict(p)
    assert d["expected_cols"] == 8                       # 只组里有
    assert d["chars_per_line"] == 22                     # 书压组
    assert d["params"]["align_ref"] == {"coord_dp": True, "coord_relaxed": False}
    assert "meta" not in d
    assert bc.provenance(p)["expected_cols"] == "组 wyg@1"
    prov = bc.params_provenance(p, {})
    assert prov["align_ref.coord_dp"] == (True, "组 wyg@1") and prov["align_ref.coord_relaxed"][1] == "基础配置"


def test_same_effective_when_book_keeps_duplicates(ws):
    """入组时书里与组同值的键先不删（旧 cv 不认组层）：生效字典除 groups 外与入组前逐键相同。"""
    book = {"expected_cols": 8, "params": {"align_ref": {"coord_dp": True}}}
    _w(ws / "config" / "book_defaults.yaml", book)
    p = _w(ws / "books" / "v1.yaml", VOL)
    before = bc.effective_book_dict(p)
    _group("wyg", 1, book)
    _w(ws / "config" / "book_defaults.yaml", {**book, "groups": {"config": "wyg@1"}})
    after = bc.effective_book_dict(p)
    after.pop("groups")
    assert after == before


def test_missing_group_copy_is_an_error(ws):
    _w(ws / "config" / "book_defaults.yaml", {"groups": {"config": "wyg@2"}})
    p = _w(ws / "books" / "v1.yaml", VOL)
    with pytest.raises(bc.BookConfigError, match="guji db pull"):
        bc.effective_book_dict(p)


@pytest.mark.parametrize("doc", [
    {"book_id": "x"}, {"corpus": 3}, {"references": []}, {"codepoints": {"a": "b"}}, {"src_w": 1600},
    {"outer_gap": {"top": 1}}, {"params": {"char_decide": {"follow_ref": "a=b"}}},
    {"params": {"align_ref": {"page_pins": "p.jsonl"}}},
    {"params": {"group_decision": {"handling": {"x": {"methods": ["a"]}}}}},
])
def test_group_forbidden_keys(ws, doc):
    _group("wyg", 1, doc)
    _w(ws / "config" / "book_defaults.yaml", {"groups": {"config": "wyg@1"}})
    p = _w(ws / "books" / "v1.yaml", VOL)
    with pytest.raises(bc.BookConfigError):
        bc.effective_book_dict(p)


def test_group_decision_handling_without_methods_ok(ws):
    _group("wyg", 1, {"params": {"group_decision": {"handling": {"x": {"mode": "a"}}}}})
    _w(ws / "config" / "book_defaults.yaml", {"groups": {"config": "wyg@1"},
                                               "params": {"group_decision": {"handling": {"y": {"mode": "b"}}}}})
    p = _w(ws / "books" / "v1.yaml", VOL)
    h = bc.effective_book_dict(p)["params"]["group_decision"]["handling"]
    assert h == {"x": {"mode": "a"}, "y": {"mode": "b"}}           # 映射深合并


def test_old_admit_key_in_group_folds(ws):
    """组里写旧键 seed_admit、书里写新键 char_decide：合层后只剩 char_decide（CV4 11-28）。"""
    _group("wyg", 1, {"params": {"seed_admit": {"alt_require_matched": True}}})
    _w(ws / "config" / "book_defaults.yaml", {"groups": {"config": "wyg@1"},
                                               "params": {"char_decide": {"lane_header_formula": True}}})
    p = _w(ws / "books" / "v1.yaml", VOL)
    ps = bc.effective_book_dict(p)["params"]
    assert "seed_admit" not in ps
    assert ps["char_decide"] == {"alt_require_matched": True, "lane_header_formula": True}


def test_groups_only_in_book_layer(ws, monkeypatch):
    p = _w(ws / "books" / "v1.yaml", {**VOL, "groups": {"config": "wyg@1"}})
    with pytest.raises(bc.BookConfigError, match="groups"):
        bc.effective_book_dict(p)
    _w(ws / "books" / "v1.yaml", VOL)
    monkeypatch.setenv(bc.OVERRIDE_ENV, json.dumps({"groups": {"config": "wyd@1"}}))
    with pytest.raises(bc.BookConfigError):
        bc.effective_book_dict(p)


@pytest.mark.parametrize("v", ["wyg", "wyg@0", "Wyg@1", "wyg@x", ["wyg@1", "wyd@1"]])
def test_bad_group_ref(v):
    with pytest.raises(bc.BookConfigError):
        bc.book_groups({"groups": {"config": v}})


def test_book_groups_and_effective_defaults(ws):
    assert bc.book_groups({}) == {"config": None, "glyph": [], "corpus": [], "model": []}
    g = bc.book_groups({"groups": {"config": "wyg@1", "glyph": "wyg", "model": ["wyg"]}})
    assert g == {"config": ("wyg", 1), "glyph": ["wyg"], "corpus": [], "model": ["wyg"]}
    _group("wyg", 1, {"expected_cols": 8, "chars_per_line": 21})
    _w(ws / "config" / "book_defaults.yaml", {"groups": {"config": "wyg@1"}, "chars_per_line": 22})
    d = bc.effective_defaults(ws)
    assert (d["expected_cols"], d["chars_per_line"]) == (8, 22)
    assert bc.effective_defaults(ws / "books" / "v1.yaml") == d
