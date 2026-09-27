# -*- coding: utf-8 -*-
"""Step0 页面预检（任务卡 #54 第22条）：`steps/page_survey.py`（尺寸判据本身）
＋ `gates/border_detect_gate.py` 的第22条延伸（缺省 flag 不拦、开关打开才拦、
白名单永远只 flag）。CLI `guji survey` 的烧烟测试也在这里。

用户诉求原文：「先探测页面情况，把需要拆分的先拆了，再跑后边的，不然代价
很大」——所以判据必须**只读原图尺寸**，不依赖任何管线产物，新书第一件事
就能跑。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

import open_guji_cv.steps  # noqa: F401  注册 v2 步骤与产物种类


def _write_page(d: Path, page: int, w: int, h: int) -> None:
    Image.new("L", (w, h), color=255).save(d / f"{page}.png")


# ── survey_book()：纯尺寸判据，不碰任何产物 ──────────────────────────────
def test_survey_book_flags_odd_pages_by_ratio(tmp_path):
    from open_guji_cv.core.book import BookSpec
    from open_guji_cv.steps.page_survey import survey_book

    raw = tmp_path / "raw"
    raw.mkdir()
    # 5 张正常页（1000×1400）+ 1 张双叶横拼（2000×1400）+ 1 张偏小书脊标签（300×1400）
    for pg in range(2, 7):
        _write_page(raw, pg, 1000, 1400)
    _write_page(raw, 1, 300, 1400)     # p1：偏小，同时也是页1
    _write_page(raw, 7, 2000, 1400)    # 双叶横拼

    book = BookSpec(id="qsurvey", title="t", raw_dir=raw, pages=list(range(1, 8)))
    rows = {r.page: r for r in survey_book(book)}

    assert rows[1].p1_suspect is True
    assert rows[1].odd is True and rows[1].kind == "偏小(标签/残页)"
    assert rows[7].odd is True and rows[7].kind == "双叶横拼(1×2)"
    for pg in range(2, 7):
        assert rows[pg].odd is False, f"p{pg} 尺寸正常不该被标异常"


def test_survey_book_2x2_and_stacked_kinds(tmp_path):
    from open_guji_cv.core.book import BookSpec
    from open_guji_cv.steps.page_survey import survey_book

    raw = tmp_path / "raw"
    raw.mkdir()
    for pg in range(1, 6):
        _write_page(raw, pg, 1000, 1400)
    _write_page(raw, 6, 2000, 2800)   # 宽高都超 1.3× → 多叶合扫
    _write_page(raw, 7, 1000, 2800)   # 只高超 → 上下叠

    book = BookSpec(id="qsurvey2", title="t", raw_dir=raw, pages=list(range(1, 8)))
    rows = {r.page: r for r in survey_book(book)}
    assert rows[6].kind == "多叶合扫(2×2)"
    assert rows[7].kind == "上下叠(2×1)"


def test_survey_book_resolves_automatically_once_page_is_fixed(tmp_path):
    """"已经拆好的页会自动恢复正常"——判据只读当前原图，不留历史状态。"""
    from open_guji_cv.core.book import BookSpec
    from open_guji_cv.steps.page_survey import survey_book

    raw = tmp_path / "raw"
    raw.mkdir()
    for pg in range(1, 6):
        _write_page(raw, pg, 1000, 1400)
    _write_page(raw, 3, 2000, 1400)   # p3 先是双叶合扫

    book = BookSpec(id="qsurvey3", title="t", raw_dir=raw, pages=list(range(1, 6)))
    assert {r.page: r.odd for r in survey_book(book)}[3] is True

    _write_page(raw, 3, 1000, 1400)   # 拆好了，换成正常尺寸
    assert {r.page: r.odd for r in survey_book(book)}[3] is False


def test_survey_book_too_few_pages_returns_empty(tmp_path):
    """样本太少中位数没意义（单页/两页的书）——不该硬凑出一个假中位数。"""
    from open_guji_cv.core.book import BookSpec
    from open_guji_cv.steps.page_survey import survey_book

    raw = tmp_path / "raw"
    raw.mkdir()
    _write_page(raw, 1, 1000, 1400)
    _write_page(raw, 2, 1000, 1400)
    book = BookSpec(id="qtiny", title="t", raw_dir=raw, pages=[1, 2])
    assert survey_book(book) == []


# ── PageSurveyStep.run_page()：走 RunContext，测白名单挂载 ─────────────────
def test_run_page_marks_whitelisted_page(tmp_path, monkeypatch):
    from helpers import make_book, make_ctx
    from open_guji_cv.steps.page_survey import PageSurveyParams, PageSurveyStep

    raw = tmp_path / "raw"
    raw.mkdir()
    for pg in range(1, 6):
        _write_page(raw, pg, 1000, 1400)
    _write_page(raw, 2, 2000, 1400)   # p2 卷端双叶横拼，本书确认无正文

    book = make_book("qwl", raw_dir=raw, pages=list(range(1, 6)))
    ctx = make_ctx(tmp_path, book, monkeypatch=monkeypatch)
    ctx.params["page_survey"] = PageSurveyParams(whitelist={2: "卷端双叶横拼，确认无正文"})

    out = PageSurveyStep().run_page(ctx, 2)["page_survey"]
    assert out.odd is True
    assert out.whitelisted is True
    assert out.whitelist_reason == "卷端双叶横拼，确认无正文"

    out3 = PageSurveyStep().run_page(ctx, 3)["page_survey"]
    assert out3.whitelisted is False   # 没配白名单的页不受影响


def test_whitelist_empty_reason_does_not_count(tmp_path, monkeypatch):
    """白名单必须写理由——空字符串不算配置过（防止"顺手加个键、不写理由"混过去）。"""
    from helpers import make_book, make_ctx
    from open_guji_cv.steps.page_survey import PageSurveyParams, PageSurveyStep

    raw = tmp_path / "raw"
    raw.mkdir()
    for pg in range(1, 6):
        _write_page(raw, pg, 1000, 1400)
    _write_page(raw, 2, 2000, 1400)

    book = make_book("qwl2", raw_dir=raw, pages=list(range(1, 6)))
    ctx = make_ctx(tmp_path, book, monkeypatch=monkeypatch)
    ctx.params["page_survey"] = PageSurveyParams(whitelist={2: "   "})

    out = PageSurveyStep().run_page(ctx, 2)["page_survey"]
    assert out.whitelisted is False


# ── border_detect_gate：缺省 flag 不拦／开关拦／白名单永远不拦 ────────────
def _gate_ctx(tmp_path, monkeypatch, raw_dir, pages, borders):
    from helpers import make_book, make_ctx
    from open_guji_cv.core.spec import page_key

    book = make_book("qgate", raw_dir=raw_dir, pages=pages)
    ctx = make_ctx(tmp_path, book, monkeypatch=monkeypatch)
    ctx.store.write(book.id, "border_detect", page_key(pages[0] if len(pages) == 1 else 2),
                    {"borders": borders})
    return book, ctx


def test_border_detect_gate_default_flags_not_rejects_odd_page(tmp_path, monkeypatch):
    from helpers import make_book, make_borders, make_ctx
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.gates.border_detect_gate import BorderDetectGateStep
    from open_guji_cv.steps.page_survey import PageSurveyStep

    raw = tmp_path / "raw"
    raw.mkdir()
    for pg in range(1, 6):
        _write_page(raw, pg, 1000, 1400)
    _write_page(raw, 2, 2000, 1400)

    book = make_book("qgate1", raw_dir=raw, pages=list(range(1, 6)), expected_cols=9)
    ctx = make_ctx(tmp_path, book, monkeypatch=monkeypatch)
    ctx.store.write(book.id, "page_survey", page_key(2),
                    PageSurveyStep().run_page(ctx, 2))
    ctx.store.write(book.id, "border_detect", page_key(2),
                    {"borders": make_borders(2000, 1400, 9)})

    gm = BorderDetectGateStep().run_page(ctx, 2)["border_detect_gate_manifest"]
    assert gm.admitted is True, gm.reject   # 缺省不拦
    assert any("page_size_odd" in f for f in gm.flags)


def test_border_detect_gate_blocks_when_switch_on(tmp_path, monkeypatch):
    from helpers import make_book, make_borders, make_ctx
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.gates.border_detect_gate import BorderDetectGateParams, BorderDetectGateStep
    from open_guji_cv.steps.page_survey import PageSurveyStep

    raw = tmp_path / "raw"
    raw.mkdir()
    for pg in range(1, 6):
        _write_page(raw, pg, 1000, 1400)
    _write_page(raw, 2, 2000, 1400)

    book = make_book("qgate2", raw_dir=raw, pages=list(range(1, 6)), expected_cols=9)
    ctx = make_ctx(tmp_path, book, monkeypatch=monkeypatch)
    ctx.store.write(book.id, "page_survey", page_key(2),
                    PageSurveyStep().run_page(ctx, 2))
    ctx.store.write(book.id, "border_detect", page_key(2),
                    {"borders": make_borders(2000, 1400, 9)})
    ctx.params["border_detect_gate"] = BorderDetectGateParams(page_survey_block=True)

    gm = BorderDetectGateStep().run_page(ctx, 2)["border_detect_gate_manifest"]
    assert gm.admitted is False
    assert any("page_size_odd" in r and "待拆/待核" in r for r in gm.reject)


def test_border_detect_gate_whitelist_overrides_switch(tmp_path, monkeypatch):
    """白名单页即使开着拦截开关也不拦——书 yaml 写明理由的页不该被一刀切。"""
    from helpers import make_book, make_borders, make_ctx
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.gates.border_detect_gate import BorderDetectGateParams, BorderDetectGateStep
    from open_guji_cv.steps.page_survey import PageSurveyParams, PageSurveyStep

    raw = tmp_path / "raw"
    raw.mkdir()
    for pg in range(1, 6):
        _write_page(raw, pg, 1000, 1400)
    _write_page(raw, 2, 2000, 1400)

    book = make_book("qgate3", raw_dir=raw, pages=list(range(1, 6)), expected_cols=9)
    ctx = make_ctx(tmp_path, book, monkeypatch=monkeypatch)
    ctx.params["page_survey"] = PageSurveyParams(whitelist={2: "卷端双叶横拼，确认无正文"})
    ctx.store.write(book.id, "page_survey", page_key(2),
                    PageSurveyStep().run_page(ctx, 2))
    ctx.store.write(book.id, "border_detect", page_key(2),
                    {"borders": make_borders(2000, 1400, 9)})
    ctx.params["border_detect_gate"] = BorderDetectGateParams(page_survey_block=True)

    gm = BorderDetectGateStep().run_page(ctx, 2)["border_detect_gate_manifest"]
    assert gm.admitted is True, gm.reject
    assert any("已列入白名单" in f for f in gm.flags)


def test_border_detect_gate_untouched_when_no_page_survey_product(tmp_path, monkeypatch):
    """`page_survey` 是 optional_consumes——没跑过这一步的书（旧产物/没接这条链）
    不该受影响，闸照旧只看 borders。"""
    from helpers import make_book, make_borders, make_ctx
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.gates.border_detect_gate import BorderDetectGateStep

    raw = tmp_path / "raw"
    raw.mkdir()
    for pg in range(1, 4):
        _write_page(raw, pg, 1000, 1400)
    book = make_book("qgate4", raw_dir=raw, pages=[1, 2, 3], expected_cols=9)
    ctx = make_ctx(tmp_path, book, monkeypatch=monkeypatch)
    ctx.store.write(book.id, "border_detect", page_key(2),
                    {"borders": make_borders(1000, 1400, 9)})

    gm = BorderDetectGateStep().run_page(ctx, 2)["border_detect_gate_manifest"]
    assert gm.admitted is True
    assert not any("page_size_odd" in f for f in gm.flags)


# ── CLI 烧烟测试 ─────────────────────────────────────────────────────────
def test_cmd_survey_smoke(tmp_path, monkeypatch, capsys):
    import argparse
    from open_guji_cv.cli_v2 import cmd_survey
    from open_guji_cv.core.book import BookSpec
    from open_guji_cv.core import book as book_mod

    raw = tmp_path / "raw"
    raw.mkdir()
    for pg in range(1, 6):
        _write_page(raw, pg, 1000, 1400)
    _write_page(raw, 1, 300, 1400)

    fake = BookSpec(id="qcli", title="t", raw_dir=raw, pages=list(range(1, 6)))
    monkeypatch.setattr(book_mod, "load_book", lambda *_a, **_k: fake)
    args = argparse.Namespace(book="qcli", pages=None, ratio_high=None, ratio_low=None,
                              json=None)
    cmd_survey(args)
    out = capsys.readouterr().out
    assert "p1" in out and "共 5 页" in out
