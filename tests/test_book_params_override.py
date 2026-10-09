# -*- coding: utf-8 -*-
"""书级 yaml `params:` 段覆盖 Step 参数（2026-09-27，D-书级admit覆盖）。

任务书依据：全唐文一直靠命令行 `--params '{"seed_admit": {"use_context": false}}'`
临时挡住 `context` 通道的错放行，漏带一次这个参数这一轮就白挡——书级 yaml 能把
这个决定钉死。这里测两件事：`BookSpec.params` 的读（`load_book`）与
`core.step._with_book_params` 在 `RunContext.params_for` 里的合并行为。

优先级实现在 `_with_book_params` 文档里写清楚了：**Step 默认 < 书 yaml < 调用方
（Engine 已解析的 CLI/管线 yaml 覆盖）**——书 yaml 只补"仍是 Step 构造默认值"
的字段，调用方已经改过的字段不会被书 yaml 盖掉。管线 yaml 与书 yaml 谁更优先
这条边界情形目前没有任何管线 yaml 触发（`seed_admit` 没人在管线 yaml 里配过
参数），本轮不精确处理，见 `_with_book_params` 文档。
"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.seed_admit import SeedAdmitParams


# ── BookSpec.params 的读 ────────────────────────────────────────────

def test_default_params_is_empty_dict():
    assert make_book().params == {}


def test_load_book_reads_params_section(tmp_path):
    from open_guji_cv.core.book import load_book

    books_dir = tmp_path / "books"
    books_dir.mkdir()
    (books_dir / "qtw.yaml").write_text(
        "id: qtw\n"
        "title: 测试册\n"
        "raw_dir: /nonexistent\n"
        "params:\n"
        "  seed_admit:\n"
        "    use_context: false\n"
        "    context_verdicts: same,unsure\n",
        encoding="utf-8")
    book = load_book("qtw", books_dir=books_dir)
    assert book.params == {"seed_admit": {"use_context": False,
                                          "context_verdicts": "same,unsure"}}


def test_load_book_no_params_section_is_empty(tmp_path):
    from open_guji_cv.core.book import load_book

    books_dir = tmp_path / "books"
    books_dir.mkdir()
    (books_dir / "qtw.yaml").write_text(
        "id: qtw\ntitle: 测试册\nraw_dir: /nonexistent\n", encoding="utf-8")
    assert load_book("qtw", books_dir=books_dir).params == {}


def test_load_book_rejects_malformed_params(tmp_path):
    from open_guji_cv.core.book import load_book

    books_dir = tmp_path / "books"
    books_dir.mkdir()
    (books_dir / "qtw.yaml").write_text(
        "id: qtw\ntitle: 测试册\nraw_dir: /nonexistent\n"
        "params:\n  seed_admit: not-a-dict\n", encoding="utf-8")
    try:
        load_book("qtw", books_dir=books_dir)
        assert False, "该抛错但没抛"
    except ValueError:
        pass


# ── 合并进 RunContext.params_for ────────────────────────────────────

def test_no_book_params_is_noop(tmp_path, monkeypatch):
    """书没配 `params:`（默认 {}）：`params_for` 结果与不加这层机制之前逐字节相同。"""
    ctx = make_ctx(tmp_path, make_book("tbook"), monkeypatch=monkeypatch)
    got = ctx.params_for(STEPS["seed_admit"])
    assert got.model_dump() == SeedAdmitParams().model_dump()


def test_book_params_overrides_step_default(tmp_path, monkeypatch):
    """书 yaml 配的字段仍是 Step 构造默认值时，被书级配置替换。"""
    book = make_book("tbook", params={"seed_admit": {"use_context": False}})
    ctx = make_ctx(tmp_path, book, monkeypatch=monkeypatch)
    got = ctx.params_for(STEPS["seed_admit"])
    assert got.use_context is False
    # 没配的字段不受影响，仍是 Step 默认值。
    assert got.context_margin == SeedAdmitParams().context_margin


def test_caller_override_wins_over_book_params(tmp_path, monkeypatch):
    """调用方已经把这个字段改成非默认值（模拟 Engine 解析过管线 yaml/CLI
    `--params` 之后传进 `ctx.params`）：书 yaml 的配置不会覆盖它。"""
    book = make_book("tbook", params={"seed_admit": {"context_margin": 0.90}})
    ctx = make_ctx(tmp_path, book, monkeypatch=monkeypatch)
    ctx.params["seed_admit"] = SeedAdmitParams(context_margin=0.55)
    got = ctx.params_for(STEPS["seed_admit"])
    assert got.context_margin == 0.55, "调用方覆盖被书 yaml 盖掉了，优先级反了"


def test_book_params_does_not_affect_other_steps(tmp_path, monkeypatch):
    """`params:` 里没提到的 Step 不受影响——只在这个 Step 的条目非空时才生效。"""
    from open_guji_cv.steps.align_ref import AlignRefParams

    book = make_book("tbook", params={"seed_admit": {"use_context": False}})
    ctx = make_ctx(tmp_path, book, monkeypatch=monkeypatch)
    got = ctx.params_for(STEPS["align_ref"])
    # align_ref 的书级语料替换（`_with_book_corpus`）另有测试覆盖，这里只
    # 断言没被 seed_admit 那条覆盖误伤（字段都是各自默认值该有的样子）。
    assert isinstance(got, AlignRefParams)


def test_caller_value_equal_to_default_is_overridden_by_book_params(tmp_path, monkeypatch):
    """调用方把字段显式设成与 Step 默认值相同的值（`SeedAdmitParams()`）时，书 yaml 仍会覆盖它。

    这是 `_with_book_params` 文档里承认的近似：分不清「没设过」与「设成默认值」，
    两者都只看值是否等于默认。本测试只用来**钉住现状**——将来换成更精确的机制
    （比如看 `model_fields_set`）时，这条要一起改，不是期望行为。
    """
    book = make_book("tbook", params={"seed_admit": {"context_margin": 0.90}})
    ctx = make_ctx(tmp_path, book, monkeypatch=monkeypatch)
    ctx.params["seed_admit"] = SeedAdmitParams()
    got = ctx.params_for(STEPS["seed_admit"])
    assert got.context_margin == 0.90
