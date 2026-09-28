# -*- coding: utf-8 -*-
"""`guji cache build-font-index`（任务书-K-控制台常驻内存，2026-09-28）：
云端预建控制台 K19 的 HOG 字体索引，随快照/发布分发，服务器只读盘。

打桩 `_rare_charsets` 回几个字的小表，只验证 CLI 接到 `index_ready`/`warm`/
`_index_key` 的路径没接错、文件写到了预期位置、第二次调用不重建。不碰真实
DEFAULT_CORPUS 规模（同 `test_cli_build_rare_index_uses_book_charsets_and_dedupes`
的分寸）。
"""
from __future__ import annotations

from argparse import Namespace

from open_guji_cv import cli_v2
from open_guji_cv.clustering import font_candidates as fc
from open_guji_cv.clustering import rare_panel as rare_panel_mod


def test_cli_build_font_index_uses_rare_charsets_and_dedupes(monkeypatch, ws):
    cs_small = tuple("一二三")
    cs_big = tuple("一二三十土王")   # small ⊆ big

    monkeypatch.setattr(rare_panel_mod, "_rare_charsets", lambda corpus=None: (cs_small, cs_big))
    monkeypatch.setattr("open_guji_cv.steps.align_ref.book_corpus", lambda book: None)

    args = Namespace(book="")
    cli_v2._cmd_cache_build_font_index(args)

    key_small = fc._index_key(cs_small, "fonts", "hog")
    key_big = fc._index_key(cs_big, "fonts", "hog")
    f_small = fc._index_dir() / f"{key_small}.npz"
    f_big = fc._index_dir() / f"{key_big}.npz"

    assert f_big.exists(), "CLI 应该已经把大表索引建出来了"
    assert not f_small.exists(), (
        "small ⊆ big：small 不该单独建索引文件（K19 去重，见 font_candidates.warm()）")
    assert not fc.index_ready(cs_small), "small 从没有属于自己的 .npz——这是设计使然"
    assert fc.all_ready([cs_small, cs_big]), "但整批算「已就绪」：small 的查询借用 big 的矩阵"

    # 第二次调用：两张表都已就绪，不该重建（用 mtime 没变来判断）
    mtime_before = f_big.stat().st_mtime_ns
    cli_v2._cmd_cache_build_font_index(args)
    assert f_big.stat().st_mtime_ns == mtime_before


def test_cli_build_font_index_passes_book_corpus_when_book_given(monkeypatch, ws):
    """给了 `--book` 时字表要按那本书的语料算（`book_corpus(book)`），
    不能悄悄退回 DEFAULT_CORPUS——预建的表要跟那本书 `rare_for(book=...)`
    实际查询时用的表对上。"""
    seen_corpus = []

    def _fake_book_corpus(book):
        seen_corpus.append(book)
        return "/fake/corpus.txt"

    def _fake_rare_charsets(corpus=None):
        assert corpus == "/fake/corpus.txt"
        return tuple("一"), tuple("一二")

    monkeypatch.setattr(rare_panel_mod, "_rare_charsets", _fake_rare_charsets)
    monkeypatch.setattr("open_guji_cv.steps.align_ref.book_corpus", _fake_book_corpus)

    cli_v2._cmd_cache_build_font_index(Namespace(book="vol01"))
    assert seen_corpus == ["vol01"]


def test_cli_build_font_index_without_workspace_refuses(monkeypatch, capsys):
    """不给 -w（也没 GUJI_CACHE_DIR）：默认语料与 cache/font_index/ 都会退回仓内样本，
    建出来的表谁也用不上——直接拒，不悄悄建（overview#246）。"""
    import pytest
    called = []
    monkeypatch.setattr(rare_panel_mod, "_rare_charsets", lambda corpus=None: called.append(1))
    with pytest.raises(SystemExit):
        cli_v2._cmd_cache_build_font_index(Namespace(book=""))
    assert "-w" in capsys.readouterr().err and not called


def test_cache_without_book_parses_with_and_without_workspace(tmp_path, monkeypatch):
    """`guji cache build-font-index -w <ws>`（不带 --book）原先被「带 book 的命令必须有
    books/<book>.yaml」那层包装拦下（`books/.yaml` 不存在），怎么都跑不起来；
    `guji cache usage` 不带 -w 也被拦。现在可选的 --book 没给时：有 -w 只查目录、导出
    GUJI_WORKSPACE；没 -w 就不碰工作区。"""
    import argparse
    import os

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    cli_v2.register_subcommands(sub)
    seen = []
    monkeypatch.setattr(cli_v2, "_cmd_cache_build_font_index",
                        lambda a: seen.append(os.environ.get("GUJI_WORKSPACE")))
    args = parser.parse_args(["cache", "build-font-index", "-w", str(tmp_path)])
    cli_v2.COMMANDS_V2["cache"](args)
    assert seen == [str(tmp_path.resolve())]

    monkeypatch.delenv("GUJI_WORKSPACE", raising=False)
    args = parser.parse_args(["cache", "build-font-index"])
    cli_v2.COMMANDS_V2["cache"](args)
    assert seen[-1] is None
