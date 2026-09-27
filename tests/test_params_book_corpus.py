# -*- coding: utf-8 -*-
"""`RunContext.params_for` 按册换语料：**指纹与 run_page 必须拿到同一份**（2026-09-21）。

原先换语料只发生在 `run_page` 里（`steps/align_ref._with_book_corpus`），而
`Engine.fingerprint()` 拿的是没换过的参数——两边算出不同的 `corpus_fingerprint`，
于是 `align_ref` / `context_decide` **永远判过期，跑多少次都洗不掉**。
bxgb 实测：引擎按不存在的 `zongmu_wenyuange_wikisource.txt` 算，run_page 按
`beixingrilu_jiaoduiben.txt` 算，产物里记的又是第三个值。

四庫總目因缺省值恰好就是它自己的语料，这个错在那本书上**看不出来**——所以这里
用一本"语料不是缺省值"的假书来钉。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import open_guji_cv.steps  # noqa: F401  （注册 STEPS）
from open_guji_cv.core.step import STEPS, RunContext


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    """一个只够 `params_for` 用的壳：它只读 `ctx.book.id`。"""
    corpus = tmp_path / "mybook.txt"
    corpus.write_text("甲乙丙丁", encoding="utf-8")
    monkeypatch.setattr("open_guji_cv.steps.align_ref.book_corpus",
                        lambda book: str(corpus), raising=True)
    c = RunContext(SimpleNamespace(id="mybook"), store=None, cache=None, log=lambda s: None)
    return c, str(corpus)


@pytest.mark.parametrize("sid", ["align_ref", "context_decide"])
def test_params_for_swaps_in_the_books_own_corpus(ctx, sid):
    c, corpus = ctx
    p = c.params_for(STEPS[sid])
    assert p.corpus == corpus, "没换成本册自己的语料"
    assert p.corpus_fingerprint, "换了语料必须重算指纹（model_copy 不触发 model_post_init）"


@pytest.mark.parametrize("sid", ["align_ref", "context_decide"])
def test_fingerprint_side_and_run_page_side_agree(ctx, sid):
    """两处拿到的是同一份——这正是这个 bug 的判据。"""
    c, _ = ctx
    from open_guji_cv.steps.align_ref import _with_book_corpus
    a = c.params_for(STEPS[sid])                    # 引擎判指纹走这条
    b = _with_book_corpus(a, c)                     # run_page 里再走一次（现在是幂等的）
    assert a.corpus == b.corpus
    assert a.corpus_fingerprint == b.corpus_fingerprint


def test_explicit_params_are_not_overridden(ctx, tmp_path):
    """显式传了 corpus 的照用不误。"""
    c, _ = ctx
    mine = tmp_path / "explicit.txt"
    mine.write_text("戊己庚辛", encoding="utf-8")
    step = STEPS["context_decide"]
    # `spec.params` 就是参数类本身（不是工厂），别写成 `spec.params()(…)`
    c.params = {"context_decide": step.spec.params(corpus=str(mine))}
    assert c.params_for(step).corpus == str(mine)


def test_steps_without_corpus_are_untouched(ctx):
    c, _ = ctx
    for sid in ("glyph_match", "row_segment", "seed_admit"):
        p = c.params_for(STEPS[sid])
        assert not hasattr(p, "corpus")


def test_general_corpus_dir_is_anchored_to_repo_not_cwd(tmp_path, monkeypatch):
    """泛古籍语料的相对路径锚**仓根**，不随进程 cwd 变（2026-09-21 第二个同型 bug）。

    `general_corpus_dir` 缺省 `corpus/external`。原先直接 `Path(...)` 解析：
    跑管线时 cwd 在工作区（扫不到）、查 status 时在 cv 仓（扫得到两份），同一份参数
    算出两个 `corpus_fingerprint`——`context_decide` 跑完立刻又判过期，循环无解。
    """
    from open_guji_cv.core.engine import params_hash
    from open_guji_cv.steps.context_decide import ContextDecideParams

    corpus = tmp_path / "mybook.txt"
    corpus.write_text("甲乙丙丁", encoding="utf-8")
    mk = lambda: ContextDecideParams(corpus=str(corpus), corpus_fingerprint="")  # noqa: E731

    monkeypatch.chdir(tmp_path)
    a = mk()
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)   # cv 仓根
    b = mk()
    assert a.corpus_fingerprint == b.corpus_fingerprint, "指纹随 cwd 变了"
    assert params_hash(a) == params_hash(b)
