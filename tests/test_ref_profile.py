"""参校本属性 reference_profile／书级 5b 字表 rare_charset（2026-11-08，参校本属性 A 块）：
写法、校验、三层合并、按页查询、B 块翻译函数；未声明的册行为与指纹不变。"""
from __future__ import annotations

import json

import pytest
import yaml

from helpers import make_book
from open_guji_cv.core import book_config as bc
from open_guji_cv.core import ref_profile as RP
from open_guji_cv.core.book import load_book

REFS = [{"file": "qtw_front_wiki.txt", "label": "wiki", "quality": "mid"},
        {"file": "qtw_kanripo.txt", "label": "kanripo", "quality": "best", "line_is_column": False}]
BOOK = {"id": "v1", "title": "t", "raw_dir": "raw", "expected_cols": 9, "pages": ["1-200"]}


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


def test_undeclared_is_column_everywhere():
    prof = RP.load_reference_profile(None, REFS)
    assert not prof.declared and prof.default == "column"
    assert prof.kind_of(1) == prof.kind_of(999) == "column"
    assert prof.ref_of(5, REFS) is REFS[0]                      # 同今天 book_corpus() 取 references[0]
    assert prof.page_token(5) is None
    b = make_book()
    assert not b.reference_profile.declared and b.rare_charset is None
    assert RP.ref_none_pages(b, [1, 2]) == [] and RP.ref_text_pages(b, [1, 2]) == []


def test_qtw001_example():
    raw = {"default": "none", "segments": [{"pages": ["35-64"], "kind": "text", "ref": "wiki", "note": "职名、凡例"}]}
    prof = RP.load_reference_profile(raw, REFS)
    assert prof.declared
    assert prof.kind_of(35) == prof.kind_of(64) == "text" and prof.kind_of(65) == prof.kind_of(1) == "none"
    assert prof.ref_of(40, REFS)["label"] == "wiki" and prof.ref_of(100, REFS) is None
    pages = range(1, 194)
    assert prof.summary(pages) == {"declared": True, "column": 0, "text": 30, "none": 163}
    assert prof.page_token(40) == "text:0" and prof.page_token(100) == "none:None"
    b = make_book(references=REFS, reference_profile=prof, pages=list(pages))
    assert RP.ref_text_pages(b) == list(range(35, 65))
    assert RP.ref_none_pages(b, [1, 50, 100]) == [1, 100]


def test_scalar_shorthand_and_explicit_column_token():
    assert RP.load_reference_profile("none", []).kind_of(3) == "none"
    prof = RP.load_reference_profile({"default": "column"}, REFS[:1])
    assert prof.declared and prof.page_token(3) is None        # 声明了 column 也不写指纹键


@pytest.mark.parametrize("raw,refs,msg", [
    ("nothing", REFS, "未知参照形态"),
    ({"default": "none", "foo": 1}, REFS, "不认识 foo"),
    ([1], REFS, "column／text／none"),
    ({"segments": [{"pages": [1], "kind": "text", "quality": "mid"}]}, REFS, "references\\[\\].quality"),
    ({"segments": [{"pages": [1]}]}, REFS, "pages、kind 都要写"),
    ({"segments": [{"pages": ["9-3"], "kind": "none"}]}, REFS, "页号写错"),
    ({"segments": [{"pages": [1.5], "kind": "none"}]}, REFS, "页号列表"),
    ({"default": "none", "segments": [{"pages": ["1-10"], "kind": "none"}, {"pages": [5], "kind": "text"}]},
     REFS, "第 5 页已在第 1 段"),
    ({"default": "none", "segments": [{"pages": [1], "kind": "text"}]}, [], "references 为空"),
    ({"default": "text"}, [], "references 为空"),
    ({"segments": [{"pages": [1], "kind": "text", "ref": "nope"}]}, REFS, "找不到"),
    ({"segments": [{"pages": [1], "kind": "none", "ref": "wiki"}]}, REFS, "不能写 ref"),
    ({"segments": [{"pages": [1], "kind": "column", "ref": "kanripo"}]}, REFS, "自相矛盾"),
    ({"segments": "1-3"}, REFS, "要写成列表"),
])
def test_validation(raw, refs, msg):
    with pytest.raises(ValueError, match=msg):
        RP.load_reference_profile(raw, refs)


def test_text_may_point_to_column_witness_and_ambiguous_ref():
    refs = [{"file": "a.txt", "label": "x", "line_is_column": True}]
    assert RP.load_reference_profile({"segments": [{"pages": [1], "kind": "text"}]}, refs).kind_of(1) == "text"
    dup = [{"file": "a.txt", "label": "x"}, {"file": "b.txt", "label": "x"}]
    with pytest.raises(ValueError, match="对上 2 项"):
        RP.load_reference_profile({"segments": [{"pages": [1], "kind": "text", "ref": "x"}]}, dup)


def test_layers_merge(ws, monkeypatch):
    _w(ws, "book_defaults.yaml", {"reference_profile": "text", "rare_charset": "qtw_all.txt"}, sub="config")
    p = _w(ws, "v1.yaml", {**BOOK, "references": REFS,
                           "reference_profile": {"segments": [{"pages": ["5-9"], "kind": "none"}]}})
    b = load_book("v1", ws / "books")
    prof = b.reference_profile
    assert prof.default == "text" and prof.kind_of(5) == "none" and prof.kind_of(10) == "text"   # 继承基础配置的 default
    assert b.rare_charset == "qtw_all.txt"
    monkeypatch.setenv(bc.OVERRIDE_ENV, json.dumps({"reference_profile": "none"}))             # 标量覆盖不丢下层 segments
    prof = load_book("v1", ws / "books").reference_profile
    assert prof.default == "none" and prof.kind_of(5) == "none" and len(prof.segments) == 1
    monkeypatch.setenv(bc.OVERRIDE_ENV, json.dumps({"reference_profile": None}))                # null 回未声明
    assert not load_book("v1", ws / "books").reference_profile.declared
    assert p.exists()


def test_segments_forbidden_in_book_defaults(ws):
    _w(ws, "v1.yaml", {**BOOK, "references": REFS})
    _w(ws, "book_defaults.yaml", {"reference_profile": {"segments": [{"pages": [1], "kind": "none"}]}}, sub="config")
    with pytest.raises(ValueError, match="基础配置.*segments 不许"):
        load_book("v1", ws / "books")


def test_load_book_error_names_volume(ws):
    _w(ws, "v1.yaml", {**BOOK, "reference_profile": "text"})
    with pytest.raises(ValueError, match="册 v1：.*references 为空"):
        load_book("v1", ws / "books")
    _w(ws, "v2.yaml", {**BOOK, "id": "v2", "rare_charset": ["a"]})
    with pytest.raises(ValueError, match="rare_charset"):
        load_book("v2", ws / "books")


def test_lint_hints():
    b = make_book(references=[], pages=[1, 2])
    assert any("四库总目" in h for h in RP.lint(b))
    prof = RP.load_reference_profile({"default": "none", "segments": [{"pages": [1, 300], "kind": "none"}]}, REFS)
    b = make_book(references=REFS, reference_profile=prof, pages=[1, 2])
    hs = RP.lint(b)
    assert any("不在本册页集" in h for h in hs) and any("没有一页用它" in h for h in hs)
    prof = RP.load_reference_profile({"default": "text", "segments": [{"pages": [1], "kind": "text", "ref": "wiki"}]}, REFS)
    hs = RP.lint(make_book(references=REFS, reference_profile=prof, pages=[1, 2], page_kinds={"cover": [1]}))
    assert any("references[0]" in h for h in hs) and any("cover／table" in h for h in hs)
    assert RP.lint(make_book(references=REFS[:1], pages=[1])) == []


def test_rare_charset_path(monkeypatch):
    assert RP.rare_charset_path(make_book()) is None
    assert RP.rare_charset_path(make_book(rare_charset="qtw_all.txt")).endswith("qtw_all.txt")


def test_not_in_any_book_deps_and_fingerprint_unchanged():
    """L0：新字段不进任何步的 book_deps，声明与否 book_deps 取值、语料钉 token 都一样（指纹不变）。"""
    import open_guji_cv.steps  # noqa: F401  注册各步
    from open_guji_cv.core.corpus_pin import step_pin_token
    from open_guji_cv.core.engine import book_dep_values
    from open_guji_cv.core.step import STEPS
    prof = RP.load_reference_profile("none", [])
    a, b = make_book(), make_book(reference_profile=prof, rare_charset="x.txt")
    for sid, step in STEPS.items():
        assert not {"reference_profile", "rare_charset"} & set(step.spec.book_deps), sid
        assert book_dep_values(step, a) == book_dep_values(step, b), sid
        assert step_pin_token(sid, a) == step_pin_token(sid, b), sid


def test_manager_facade_exports():
    from open_guji_cv import manager_api
    assert manager_api.RefProfile is RP.RefProfile
    assert manager_api.load_reference_profile is RP.load_reference_profile
    assert manager_api.ref_profile_lint is RP.lint
