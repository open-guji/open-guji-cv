"""册配置分层与运行覆盖（doc/design/册配置分层与运行覆盖.md）。"""
from __future__ import annotations

import json

import pytest
import yaml

from open_guji_cv.core import book_config as bc
from open_guji_cv.core.book import load_book

BOOK = {"id": "v1", "title": "t", "raw_dir": "raw", "corpus": 22, "cv_version": "0.5.19", "expected_cols": 9,
        "params": {"seed_admit": {"shadow_veto": True, "x": 1}}}


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


def test_merge_rules():
    base = {"a": {"b": 1, "c": 2}, "l": [1, 2], "s": 1, "params": {"seed_admit": {"p": 1, "q": 2}}}
    over = {"a": {"b": 9}, "l": [3], "s": None, "params": {"seed_admit": {"p": None}}}
    out = bc.merge(base, over)
    assert out["a"] == {"b": 9, "c": 2}
    assert out["l"] == [3]                      # 列表整体替换
    assert out["s"] is None                     # 普通字段的 null 就是 null（expected_cols: null 有意义）
    assert out["params"]["seed_admit"] == {"q": 2}   # params 里的 null = 去掉、回 Step 默认
    assert base["a"]["b"] == 1                  # 不改入参


def test_no_layers_is_identity(ws):
    p = _w(ws, "v1.yaml", BOOK)
    assert bc.effective_book_dict(p) == BOOK


def test_defaults_then_book_then_override(ws, monkeypatch):
    p = _w(ws, "v1.yaml", {"id": "v1", "title": "t", "raw_dir": "raw", "corpus": 23})
    _w(ws, "book_defaults.yaml", {"cv_version": "0.5.21", "corpus": 22, "expected_cols": 9,
                                  "params": {"seed_admit": {"shadow_veto": True}}}, sub="config")
    d = bc.effective_book_dict(p)
    assert (d["cv_version"], d["corpus"], d["expected_cols"]) == ("0.5.21", 23, 9)   # 册覆盖基础
    assert d["params"]["seed_admit"]["shadow_veto"] is True
    monkeypatch.setenv(bc.OVERRIDE_ENV, json.dumps({"corpus": 24, "params": {"seed_admit": {"shadow_veto": False}}}))
    d = bc.effective_book_dict(p)
    assert d["corpus"] == 24 and d["params"]["seed_admit"]["shadow_veto"] is False
    assert bc.provenance(p)["corpus"] == "运行覆盖" and bc.provenance(p)["cv_version"] == "基础配置"


def test_defaults_forbid_identity_and_measured(ws):
    p = _w(ws, "v1.yaml", BOOK)
    _w(ws, "book_defaults.yaml", {"bottom_gap": 10.0}, sub="config")
    with pytest.raises(bc.BookConfigError, match="bottom_gap"):
        bc.effective_book_dict(p)


def test_override_forbids_identity(ws, monkeypatch):
    p = _w(ws, "v1.yaml", BOOK)
    monkeypatch.setenv(bc.OVERRIDE_ENV, json.dumps({"raw_dir": "x"}))
    with pytest.raises(bc.BookConfigError, match="raw_dir"):
        bc.effective_book_dict(p)
    monkeypatch.setenv(bc.OVERRIDE_ENV, "{bad")
    with pytest.raises(bc.BookConfigError, match="JSON"):
        bc.effective_book_dict(p)


def test_load_book_uses_layers(ws, monkeypatch):
    _w(ws, "v1.yaml", {"id": "v1", "title": "t", "raw_dir": "raw", "corpus": 22})
    _w(ws, "book_defaults.yaml", {"cv_version": "0.5.21", "params": {"seed_admit": {"shadow_veto": True}}}, sub="config")
    b = load_book("v1", ws / "books")
    assert b.cv_version == "0.5.21" and b.corpus == 22
    assert b.params["seed_admit"]["shadow_veto"] is True
    monkeypatch.setenv(bc.OVERRIDE_ENV, json.dumps({"cv_version": "0.5.20"}))
    assert load_book("v1", ws / "books").cv_version == "0.5.20"


def test_explicit_param_false_beats_book_true():
    """修坑：册 yaml 写 shadow_veto: true，调用方显式传 false（恰是默认值）要生效。"""
    from open_guji_cv.core.step import _with_book_params
    from pydantic import BaseModel

    class P(BaseModel):
        shadow_veto: bool = False
        x: int = 0

    class S:                                    # 最小的 Step／ctx 替身
        class spec:
            id = "seed_admit"
            params = P

    class Ctx:
        class book:
            params = {"seed_admit": {"shadow_veto": True, "x": 5}}

    got = _with_book_params(P(shadow_veto=False), S, Ctx)
    assert got.shadow_veto is False and got.x == 5      # 显式的 false 不被改回；没传的 x 仍取册值
    assert _with_book_params(P(), S, Ctx).shadow_veto is True   # 没显式传：册值生效（行为同以前）
