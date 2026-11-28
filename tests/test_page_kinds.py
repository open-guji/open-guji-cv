"""页型表 page_kinds（2026-11-04 页型表第 1 步）：新写法与老的三个 Step 参数逐值相同，指纹不动。"""
from __future__ import annotations

import dataclasses
import json

import pytest
import yaml

from helpers import make_book
from open_guji_cv.core import book_config as bc
from open_guji_cv.core import page_kinds as PK
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import STEPS

OLD = {"border_detect_gate": {"body_pages": [88, 90], "table_pages": ["8-163"]},
       "row_segment": {"roster_pages": ["89-132"]}}
NEW = {"body": [88, 90], "table": ["8-163"], "roster": ["89-132"]}
BOOK = {"id": "v1", "title": "t", "raw_dir": "raw", "expected_cols": 9}


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


def test_cover_kind_maps_to_cover_pages_and_exclusive():
    assert PK.to_params(PK.load_page_kinds({"cover": [1]})) == {"border_detect_gate": {"cover_pages": [1]}}
    assert make_book(page_kinds={"cover": [1], "body": [5]}).params["border_detect_gate"] == {"cover_pages": [1], "body_pages": [5]}
    with pytest.raises(ValueError, match="一页只能是一种页型"):
        PK.load_page_kinds({"cover": ["1-3"], "table": [2]})
    with pytest.raises(ValueError, match="一页只能是一种页型"):
        PK.load_page_kinds({"cover": [1], "body": [1]})
    PK.load_page_kinds({"roster": ["1-5"], "body": [2]})          # 职名页是正文管线里的分支，可与 body 重叠


def test_load_page_kinds_validates():
    assert PK.load_page_kinds(None) == {} and PK.load_page_kinds({}) == {}
    assert PK.load_page_kinds({"body": [], "table": None, "roster": 5}) == {"roster": [5]}
    with pytest.raises(ValueError, match="未知页型"):
        PK.load_page_kinds({"bodyy": [1]})
    with pytest.raises(ValueError, match="页号列表"):
        PK.load_page_kinds({"body": [1.5]})
    with pytest.raises(ValueError, match="页号写错"):
        PK.load_page_kinds({"table": ["10-3"]})
    with pytest.raises(ValueError, match="页型"):
        PK.load_page_kinds([1, 2])


def test_new_form_equals_old_params_and_fingerprint(tmp_path):
    from open_guji_cv.core.engine import Engine
    from open_guji_cv.core.pipeline import load_pipeline
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore

    def eng(book):
        return Engine(book, load_pipeline("keben_body_v2"), store=ProductStore(tmp_path / "p"),
                      cache=ImageCache(tmp_path / "c"), log=lambda s: None)
    old, new = make_book(params=OLD), make_book(page_kinds=NEW)
    assert new.params == old.params                       # 逐值相同
    eo, en = eng(old), eng(new)
    for sid in ("border_detect_gate", "row_segment"):
        po, pn = eo.ctx.params_for(STEPS[sid]), en.ctx.params_for(STEPS[sid])
        assert po.model_dump() == pn.model_dump()         # 进指纹的 dump 一样
    assert en.ctx.params_for(STEPS["row_segment"]).roster_pages == ["89-132"]


def test_conflict_and_idempotence():
    with pytest.raises(ValueError, match="两处都写了"):
        make_book(page_kinds={"body": [1]}, params={"border_detect_gate": {"body_pages": [2]}})
    b = make_book(page_kinds={"body": [1]}, params={"border_detect_gate": {"body_pages": [1]}})   # 值一样不算冲突
    assert dataclasses.replace(b, title="x").params == b.params                                     # replace 再跑 __post_init__ 不误报
    assert make_book().page_kinds == {} and "border_detect_gate" not in make_book().params


def test_load_book_both_forms_same(ws, monkeypatch):
    monkeypatch.setenv("GUJI_ALLOW_OLD_PAGE_SYNTAX", "1")       # 老写法的册要读得进来才能对比
    old = load_book(_w(ws, "old.yaml", {**BOOK, "id": "old", "params": OLD}).stem, ws / "books")
    new = load_book(_w(ws, "new.yaml", {**BOOK, "id": "new", "page_kinds": NEW}).stem, ws / "books")
    assert new.params == old.params
    assert new.page_kinds == old.page_kinds == {"body": [88, 90], "table": ["8-163"], "roster": ["89-132"]}


def test_layers_high_layer_wins_either_form(ws, monkeypatch):
    p = _w(ws, "v1.yaml", {**BOOK, "page_kinds": {"body": [1, 2]}})
    monkeypatch.setenv(bc.OVERRIDE_ENV, json.dumps({"params": {"border_detect_gate": {"body_pages": None}}}))
    assert "border_detect_gate" not in bc.effective_book_dict(p)["params"] or \
        "body_pages" not in bc.effective_book_dict(p)["params"]["border_detect_gate"]
    monkeypatch.setenv(bc.OVERRIDE_ENV, json.dumps({"page_kinds": {"body": [7]}}))
    assert bc.effective_book_dict(p)["params"]["border_detect_gate"]["body_pages"] == [7]
    monkeypatch.setenv(bc.OVERRIDE_ENV, json.dumps({"params": {"border_detect_gate": {"body_pages": [9]}}}))
    assert bc.effective_book_dict(p)["params"]["border_detect_gate"]["body_pages"] == [9]


def test_same_layer_conflict_names_layer(ws, monkeypatch):
    monkeypatch.setenv("GUJI_ALLOW_OLD_PAGE_SYNTAX", "1")       # 同层新老并写：先过老写法关才报冲突
    p = _w(ws, "v1.yaml", {**BOOK, "page_kinds": {"body": [1]}, "params": {"border_detect_gate": {"body_pages": [2]}}})
    with pytest.raises(ValueError, match="册 yaml：page_kinds.body"):
        bc.effective_book_dict(p)


def test_page_kinds_not_allowed_in_book_defaults(ws):
    p = _w(ws, "v1.yaml", BOOK)
    _w(ws, "book_defaults.yaml", {"page_kinds": {"body": [1]}}, sub="config")
    with pytest.raises(bc.BookConfigError):
        bc.effective_book_dict(p)


def test_params_provenance_labels_page_kinds(ws):
    p = _w(ws, "v1.yaml", {**BOOK, "page_kinds": {"table": ["8-163"]}})
    src = bc.params_provenance(p, {})
    assert src["border_detect_gate.table_pages"] == (["8-163"], "册 yaml（page_kinds）")
    p2 = _w(ws, "v2.yaml", {**BOOK, "id": "v2", "params": OLD})
    assert bc.params_provenance(p2, {})["border_detect_gate.table_pages"][1] == "册 yaml"


def test_old_syntax_rejected_but_override_and_escape_hatch_ok(ws, monkeypatch):
    p = _w(ws, "v1.yaml", {**BOOK, "params": OLD})
    monkeypatch.delenv("GUJI_ALLOW_OLD_PAGE_SYNTAX", raising=False)
    with pytest.raises(bc.BookConfigError, match="page_kinds.body"):
        bc.effective_book_dict(p)
    monkeypatch.setenv("GUJI_ALLOW_OLD_PAGE_SYNTAX", "1")            # 迁移脚本核指纹要读迁移前的册
    with pytest.warns(FutureWarning, match="page_kinds.body"):
        assert bc.effective_book_dict(p)["params"]["border_detect_gate"]["body_pages"] == [88, 90]
    monkeypatch.delenv("GUJI_ALLOW_OLD_PAGE_SYNTAX")
    import warnings
    p2 = _w(ws, "v2.yaml", {**BOOK, "id": "v2", "page_kinds": NEW})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        bc.effective_book_dict(p2)                               # 新写法不报
        monkeypatch.setenv(bc.OVERRIDE_ENV, json.dumps({"params": {"border_detect_gate": {"body_pages": [3]}}}))
        bc.effective_book_dict(p2)                               # 运行覆盖里的老字段不报（实验的正当用法）
    assert PK.old_syntax_in({"params": {"border_detect_gate": {"body_pages": []}}}) == []


def test_no_ref_kind_maps_to_seed_admit_and_swaps_params_on_those_pages_only():
    """无参校本页（脉经 林億序／牒文，2026-11-19）：page_kinds.no_ref → seed_admit.no_ref_pages，
    这些页上叠 no_ref_params，别的页原样；都没配时不进 dump（指纹不动）。"""
    from open_guji_cv.steps.seed_admit import SeedAdmitParams, no_ref_page_params
    assert PK.to_params(PK.load_page_kinds({"no_ref": ["5-7"]})) == {"seed_admit": {"no_ref_pages": ["5-7"]}}
    assert make_book(page_kinds={"no_ref": [51, 52]}).params["seed_admit"] == {"no_ref_pages": [51, 52]}
    base = SeedAdmitParams()
    assert "no_ref_pages" not in base.model_dump() and "no_ref_params" not in base.model_dump()
    p = SeedAdmitParams(no_ref_pages=["5-7"], no_ref_params={"solo_5b_cov": 0.95, "solo_5b_min_n": 1})
    assert no_ref_page_params(p, 4) is p
    q = no_ref_page_params(p, 6)
    assert (q.solo_5b_cov, q.solo_5b_min_n) == (0.95, 1) and p.solo_5b_cov is None
    with pytest.raises(ValueError, match="不认的参数"):
        no_ref_page_params(SeedAdmitParams(no_ref_pages=[1], no_ref_params={"nope": 1}), 1)
    with pytest.raises(ValueError, match="不认的参数"):
        no_ref_page_params(SeedAdmitParams(no_ref_pages=[1], no_ref_params={"no_ref_pages": [2]}), 1)


def test_no_ref_params_also_on_reference_profile_none_pages():
    """册配置 reference_profile 声明 none 的页与 page_kinds.no_ref 同一口径：no_ref_params 也叠上（参校本 bug 修 CV0 11-27）；
    text 页、未声明的册不叠；没配 no_ref_params 时原样返回同一对象（指纹不动）。"""
    import types
    from open_guji_cv.core.ref_profile import load_reference_profile
    from open_guji_cv.steps.seed_admit import SeedAdmitParams, no_ref_page_params
    prof = load_reference_profile({"default": "text", "segments": [{"pages": ["5-7"], "kind": "none"}]}, [{"file": "x.txt"}])
    book = types.SimpleNamespace(reference_profile=prof)
    p = SeedAdmitParams(no_ref_params={"solo_5b_cov": 0.95, "solo_5b_min_n": 1})
    assert (no_ref_page_params(p, 6, book).solo_5b_cov, no_ref_page_params(p, 6, book).solo_5b_min_n) == (0.95, 1)
    assert no_ref_page_params(p, 8, book) is p                     # text 页
    assert no_ref_page_params(p, 6) is p                           # 没给册（老调用）
    undeclared = types.SimpleNamespace(reference_profile=load_reference_profile(None, [{"file": "x.txt"}]))
    assert no_ref_page_params(p, 6, undeclared) is p
    bare = SeedAdmitParams()
    assert no_ref_page_params(bare, 6, book) is bare               # 没配 no_ref_params
