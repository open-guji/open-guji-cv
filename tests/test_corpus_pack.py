# -*- coding: utf-8 -*-
"""语料库清单（ops.corpus_pack）：build 递增不覆盖、verify 能发现改动／缺失／新增。自造工作区，不碰真书数据。"""
from __future__ import annotations

import json

import pytest

from open_guji_cv.ops import corpus_pack as cp


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "config" / "groups").mkdir(parents=True)
    (tmp_path / "config" / "groups" / "freq.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "ref.txt").write_text("甲乙丙", encoding="utf-8")
    return tmp_path


def _ws_items(path):
    m = json.loads(path.read_text(encoding="utf-8"))
    return {i["path"] for i in m["items"] if i["root"] == "ws"}


def test_build_numbers_increase_and_never_overwrite(ws):
    p1 = cp.build(ws)
    assert p1.parent.name == "v1"
    assert _ws_items(p1) == {"config/groups/freq.json", "corpus/ref.txt"}
    assert cp.build(ws).parent.name == "v2"
    with pytest.raises(FileExistsError):
        cp.build(ws, 1)
    assert [s["version"] for s in cp.summary(ws)] == [1, 2]


def test_verify_detects_change_missing_extra(ws):
    cp.build(ws)
    assert cp.verify(ws, 1)["clean"]
    (ws / "config" / "groups" / "freq.json").write_text('{"a": 2}', encoding="utf-8")
    (ws / "corpus" / "ref.txt").unlink()
    (ws / "corpus" / "new.txt").write_text("丁", encoding="utf-8")
    r = cp.verify(ws, 1)
    assert not r["clean"]
    assert r["changed"] == ["ws:config/groups/freq.json"]
    assert r["missing"] == ["ws:corpus/ref.txt"]
    assert r["extra"] == ["ws:corpus/new.txt"]


def test_verify_unknown_version(ws):
    with pytest.raises(FileNotFoundError):
        cp.verify(ws, 9)


# ── 册钉子（core.corpus_pin）─────────────────────────────────────────────────

def _ctx_with_ws(tmp_path, monkeypatch, corpus):
    from helpers import make_book, make_ctx
    (tmp_path / "corpus").mkdir(exist_ok=True)
    (tmp_path / "corpus" / "ref.txt").write_text("甲乙丙", encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path))
    return make_ctx(tmp_path, make_book(corpus=corpus))


def test_parse_pin():
    from open_guji_cv.core.corpus_pin import parse_pin
    assert parse_pin(None) is None and parse_pin("") is None
    assert parse_pin(3) == 3 and parse_pin("v3") == 3 and parse_pin("3") == 3
    for bad in (0, "x", "v", -1):
        with pytest.raises(ValueError):
            parse_pin(bad)


def test_pin_replaces_content_fingerprints_with_version(tmp_path, monkeypatch):
    from open_guji_cv.steps.context_decide import ContextDecideParams
    cp.build(tmp_path)                                  # v1
    unpinned = _ctx_with_ws(tmp_path, monkeypatch, None)
    p0 = unpinned.params_for(_step("context_decide"))
    assert p0.corpus_fingerprint and not p0.corpus_fingerprint.startswith("corpus-")

    pinned = _ctx_with_ws(tmp_path, monkeypatch, 1)
    p1 = pinned.params_for(_step("context_decide"))
    assert isinstance(p1, ContextDecideParams)
    assert p1.corpus_fingerprint == "corpus-v1"


def test_pinned_fingerprint_ignores_content_but_not_version(tmp_path, monkeypatch):
    cp.build(tmp_path)                                  # v1
    cp.build(tmp_path)                                  # v2
    ctx1 = _ctx_with_ws(tmp_path, monkeypatch, 1)
    before = ctx1.params_for(_step("context_decide")).corpus_fingerprint
    (tmp_path / "corpus" / "ref.txt").write_text("甲乙丙丁", encoding="utf-8")   # 内容变了
    after = _ctx_with_ws(tmp_path, monkeypatch, 1).params_for(_step("context_decide")).corpus_fingerprint
    assert before == after == "corpus-v1"
    assert _ctx_with_ws(tmp_path, monkeypatch, 2).params_for(_step("context_decide")).corpus_fingerprint == "corpus-v2"


def test_pin_without_manifest_fails_fast(tmp_path, monkeypatch):
    ctx = _ctx_with_ws(tmp_path, monkeypatch, 7)
    with pytest.raises(FileNotFoundError):
        ctx.params_for(_step("context_decide"))


def test_pin_leaves_steps_without_corpus_fields_alone(tmp_path, monkeypatch):
    cp.build(tmp_path)
    ctx = _ctx_with_ws(tmp_path, monkeypatch, 1)
    st = _step("border_detect")
    assert ctx.params_for(st) == st.spec.params()


def _step(sid):
    import open_guji_cv.steps  # noqa: F401  注册全部 Step
    from open_guji_cv.core.step import STEPS
    return STEPS[sid]
