"""`core/hooks.py`：pipeline 调钩子、manager 登记（拆分 P4）。不装 manager 也要能跑。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from open_guji_cv.core import hooks


@pytest.fixture
def empty_hooks(monkeypatch):
    monkeypatch.setattr(hooks, "_HOOKS", {p: [] for p in hooks.POINTS})
    monkeypatch.setattr(hooks, "_LOADED", True)


def test_call_in_order_and_dedup(empty_hooks):
    seen = []
    f = lambda x: seen.append(("f", x)) or 1          # noqa: E731
    g = lambda x: seen.append(("g", x)) or 2          # noqa: E731
    hooks.add("startup", f)
    hooks.add("startup", g)
    hooks.add("startup", f)
    assert hooks.call("startup", "pipeline") == [1, 2]
    assert seen == [("f", "pipeline"), ("g", "pipeline")]
    with pytest.raises(ValueError):
        hooks.add("nope", f)


def test_pinned_inputs():
    b = SimpleNamespace(glyph_pin=19, model=3, corpus="c2", corpus_dev=False)
    assert hooks.pinned_inputs(b) == ["字形库 g19", "模型 m3", "语料 c2"]
    assert hooks.pinned_inputs(SimpleNamespace()) == []
    assert hooks.pinned_inputs(SimpleNamespace(corpus="c2", corpus_dev=True)) == []


def test_prepare_refuses_pinned_book_without_manager(empty_hooks, capsys):
    from open_guji_cv import cli_v2
    eng = SimpleNamespace(book=SimpleNamespace(id="vol01", glyph_pin=19))
    with pytest.raises(SystemExit) as e:
        cli_v2._prepare(eng, ["glyph_match"])
    assert e.value.code == 2 and "guji-manager" in capsys.readouterr().err
    cli_v2._prepare(SimpleNamespace(book=SimpleNamespace(id="keben")), ["glyph_match"])   # 没钉东西：照跑


def test_prepare_uses_registered_hook(empty_hooks):
    from open_guji_cv import cli_v2
    got = []
    hooks.add("prepare", lambda book, steps, jobs: got.append((book.id, steps, jobs)))
    cli_v2._prepare(SimpleNamespace(book=SimpleNamespace(id="vol01", glyph_pin=19)), ["glyph_match"], jobs=4)
    assert got == [("vol01", ["glyph_match"], 4)]
