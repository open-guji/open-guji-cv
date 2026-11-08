"""参校本属性 C 块：Step5-b 候选字表读书级 `rare_charset`（2026-11-08）。
没写 rare_charset 的册：字表取值与指纹逐位不变；写了的册：字表取它、指纹多一个键。"""
from __future__ import annotations

from types import SimpleNamespace

from helpers import make_book
from open_guji_cv.core import engine as E
from open_guji_cv.core.ref_profile import rare_charset_path
from open_guji_cv.steps import align_ref as AR
from open_guji_cv.steps.rare_candidates import RareCandidatesStep, rare_corpus


def _ctx(book):
    logs = []
    return SimpleNamespace(book=book, log=logs.append, logs=logs)


def test_unset_keeps_old_path():
    b = make_book()
    assert rare_charset_path(b) is None
    ctx = _ctx(b)
    assert rare_corpus(ctx) == AR.book_corpus(b.id)


def test_set_uses_rare_charset(tmp_path, monkeypatch):
    f = tmp_path / "qtw_all.txt"
    f.write_text("唐文\n", encoding="utf-8")
    monkeypatch.setattr("open_guji_cv.core.workspace.corpus_path", lambda name: tmp_path / name)
    b = make_book(rare_charset="qtw_all.txt")
    assert rare_corpus(_ctx(b)) == str(f)


def test_set_but_missing_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr("open_guji_cv.core.workspace.corpus_path", lambda name: tmp_path / name)
    b = make_book(rare_charset="nope.txt")
    ctx = _ctx(b)
    assert rare_corpus(ctx) == AR.book_corpus(b.id)
    assert any("rare_charset" in m for m in ctx.logs)


def test_fingerprint_key_only_when_set():
    step = RareCandidatesStep()
    p = step.spec.params()
    from open_guji_cv.core.engine import params_hash
    ph = params_hash(p, step.spec.soft_params, step.spec.path_params)
    base = E._self_payload(step, make_book(), ph)
    assert "rare_charset" not in base
    with_rc = E._self_payload(step, make_book(rare_charset="qtw_all.txt"), ph)
    assert with_rc["rare_charset"] == "qtw_all.txt"
    assert {k: v for k, v in with_rc.items() if k != "rare_charset"} == base
