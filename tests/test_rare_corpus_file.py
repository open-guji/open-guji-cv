"""Step5-b 字表语料 `font.charset.corpus_file`（5-b 专用、与参校本脱钩；全唐文 002，形近字线 11-08）。"""
from __future__ import annotations

from types import SimpleNamespace

from open_guji_cv.steps import rare_candidates as rc


def test_unset_falls_back_to_book_corpus(monkeypatch):
    monkeypatch.setattr("open_guji_cv.steps.align_ref.book_corpus", lambda bid: f"REF:{bid}")
    assert rc.rare_corpus(SimpleNamespace(id="b", font={})) == "REF:b"
    assert rc.rare_corpus(SimpleNamespace(id="b", font=None)) == "REF:b"


def test_corpus_file_used_when_present(tmp_path, monkeypatch):
    f = tmp_path / "whole.txt"
    f.write_text("全唐文", encoding="utf-8")
    monkeypatch.setattr("open_guji_cv.steps.align_ref.book_corpus", lambda bid: f"REF:{bid}")
    monkeypatch.setattr("open_guji_cv.core.workspace.corpus_path", lambda name: tmp_path / name)
    book = SimpleNamespace(id="b", font={"charset": {"corpus_file": "whole.txt"}})
    assert rc.rare_corpus(book) == str(f)
    # 配了但文件不在：退回旧口径
    book = SimpleNamespace(id="b", font={"charset": {"corpus_file": "missing.txt"}})
    assert rc.rare_corpus(book) == "REF:b"
