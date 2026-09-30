# -*- coding: utf-8 -*-
"""issue #154：`column_review`/`slot_count_review`/`step9`/`glyph_match`/
`products`/`runs` 六个 router 的八处 `resolve_pages(pages)` 调用都改成了
`resolve_pages_ext(pages)`。这里逐个 router **直调实现体**（同
`console/errors.py` 的说法：这些路由函数本来就是"直调"与"走 HTTP"结果一致
的普通函数），验证 `list:`/`cells:` 前缀现在能正确解析成页号（不再对
`int("list:...")`／`int("cells:...")` 抛 `ValueError`），且写错前缀时返回
`HTTPException(400)`，不是裸 500。

`_isolated_env`（`tests/conftest.py` autouse）已经把 `GUJI_*` 环境变量清空、
`REPO_ROOT` 指到本条测试专属的空目录，所以 `deps.product_store()` 天然读到
空产物库——各 router 对"这一页没有产物"本就有兜底（跳过/空聚合），不需要
额外造产物，只要证明"页号解析对了、往下没有因为不认识前缀而崩"就够。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from open_guji_cv.core.book import BookSpec

from helpers import make_book


def _write_list(tmp_path, monkeypatch, name: str, lines: list[str]) -> None:
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path / "feedback"))
    lists_dir = tmp_path / "feedback" / "lists"
    lists_dir.mkdir(parents=True, exist_ok=True)
    (lists_dir / f"{name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


class _NoProductsStore:
    """没有任何产物的假 Store——`read()` 直接报没有，不用真造产物就能证明
    `pages` 解析本身对了（下游"这一页没产物"的兜底不是本卡要测的东西）。"""

    def read(self, *a, **kw):
        raise FileNotFoundError("no products in fake store")


# ── column_review ───────────────────────────────────────────────────────
def test_column_review_cases_accepts_cells_and_list(tmp_path, monkeypatch):
    from open_guji_cv.console.routers import column_review as m

    bk = make_book("vol01")
    monkeypatch.setattr(m, "load_book", lambda book: bk)
    monkeypatch.setattr(m.deps, "product_store", lambda: _NoProductsStore())

    out = m.api_column_review_cases(book="vol01", pages="cells:1:1:1")
    assert out["counts"] == {"blocking": 0, "review": 0, "clean": 0}

    _write_list(tmp_path, monkeypatch, "mylist", ["vol01:2:1:1"])
    out2 = m.api_column_review_cases(book="vol01", pages="list:mylist")
    assert out2["counts"] == {"blocking": 0, "review": 0, "clean": 0}


def test_column_review_cases_bad_cells_is_400_not_500(monkeypatch):
    from open_guji_cv.console.routers import column_review as m

    bk = make_book("vol01")
    monkeypatch.setattr(m, "load_book", lambda book: bk)

    with pytest.raises(HTTPException) as exc_info:
        m.api_column_review_cases(book="vol01", pages="cells:not-a-coordinate")
    assert exc_info.value.status_code == 400


# ── slot_count_review ────────────────────────────────────────────────────
def test_slot_count_cards_accepts_cells_and_list(tmp_path, monkeypatch):
    from open_guji_cv.console.routers import slot_count_review as m

    bk = make_book("vol01")
    monkeypatch.setattr("open_guji_cv.core.book.load_book", lambda book: bk)
    monkeypatch.setattr(m, "slot_count_cards", lambda st, book, pgs: list(pgs))

    out = m.api_slot_count_cards(book="vol01", pages="cells:1:1:1,3:2:2")
    assert out["pages"] == [1, 3]
    assert out["n"] == 2

    _write_list(tmp_path, monkeypatch, "mylist", ["vol01:5:1:1"])
    out2 = m.api_slot_count_cards(book="vol01", pages="list:mylist")
    assert out2["pages"] == [5]


def test_slot_count_cards_bad_list_is_400_not_500(monkeypatch):
    from open_guji_cv.console.routers import slot_count_review as m

    bk = make_book("vol01")
    monkeypatch.setattr("open_guji_cv.core.book.load_book", lambda book: bk)

    with pytest.raises(HTTPException) as exc_info:
        m.api_slot_count_cards(book="vol01", pages="list:does-not-exist")
    assert exc_info.value.status_code == 400


# ── step9 ────────────────────────────────────────────────────────────────
def test_step9_render_accepts_cells_and_list(tmp_path, monkeypatch):
    from open_guji_cv.console.routers import step9 as m

    bk = make_book("vol01")
    monkeypatch.setattr(m, "load_book", lambda book: bk)
    monkeypatch.setattr(m, "render_page", lambda store, book, page, stale: f"p{page}")

    out = m.api_step9_render(book="vol01", pages="cells:1:1:1,2:1:1")
    assert out["pages"] == [1, 2]
    assert out["text"] == "#第1页\np1\n#第2页\np2"

    _write_list(tmp_path, monkeypatch, "mylist", ["vol01:9:1:1"])
    out2 = m.api_step9_render(book="vol01", pages="list:mylist")
    assert out2["pages"] == [9]


def test_step9_reflow_accepts_cells(monkeypatch):
    from open_guji_cv.console.routers import step9 as m

    bk = make_book("vol01")
    monkeypatch.setattr(m, "load_book", lambda book: bk)
    monkeypatch.setattr(m, "render_page", lambda store, book, page, stale: "text")
    monkeypatch.setattr(m, "reflow_page_structured",
                        lambda store, book, page, text, baseline_kg, notes: [])

    out = m.api_step9_reflow(book="vol01", pages="cells:1:1:1")
    assert [p["page"] for p in out["pages"]] == [1]


def test_step9_progress_accepts_cells_and_bad_prefix_is_400(monkeypatch):
    from open_guji_cv.console.routers import step9 as m

    bk = make_book("vol01")
    monkeypatch.setattr(m, "load_book", lambda book: bk)
    monkeypatch.setattr("open_guji_cv.report.progress.page_progress",
                        lambda book, pages, store: {"pages": pages})

    out = m.api_step9_progress(book="vol01", pages="cells:1:1:1")
    assert out["pages"] == [1]

    with pytest.raises(HTTPException) as exc_info:
        m.api_step9_progress(book="vol01", pages="cells:not-a-coordinate")
    assert exc_info.value.status_code == 400


# ── glyph_match ───────────────────────────────────────────────────────────
def test_glyph_match_summary_accepts_cells_and_list(tmp_path, monkeypatch):
    from open_guji_cv.console.routers import glyph_match as m

    bk = make_book("vol01")
    monkeypatch.setattr(m, "load_book", lambda book: bk)
    monkeypatch.setattr("open_guji_cv.steps.glyph_match.glyph_match_summary",
                        lambda book, pages, store: {"pages": pages})

    out = m.api_glyph_match_summary(book="vol01", pages="cells:1:1:1")
    assert out["pages"] == [1]

    _write_list(tmp_path, monkeypatch, "mylist", ["vol01:7:1:1"])
    out2 = m.api_glyph_match_summary(book="vol01", pages="list:mylist")
    assert out2["pages"] == [7]

    with pytest.raises(HTTPException) as exc_info:
        m.api_glyph_match_summary(book="vol01", pages="list:does-not-exist")
    assert exc_info.value.status_code == 400


# ── products (三处：gate/align-ref/ocr-candidates 汇总) ───────────────────
def test_gate_summary_route_accepts_cells(monkeypatch):
    from open_guji_cv.console.routers import products as m

    bk = make_book("vol01")
    monkeypatch.setattr(m, "load_book", lambda book: bk)
    monkeypatch.setattr(m, "gate_summary",
                        lambda book, pages, store, gate="column_gate": {"pages": pages})

    out = m.api_gate_summary(book="vol01", pages="cells:1:1:1")
    assert out["pages"] == [1]


def test_align_ref_summary_route_accepts_cells_and_bad_is_400(monkeypatch):
    from open_guji_cv.console.routers import products as m

    bk = make_book("vol01")
    monkeypatch.setattr(m, "load_book", lambda book: bk)
    monkeypatch.setattr("open_guji_cv.steps.align_ref.align_ref_summary",
                        lambda book, pages, store: {"pages": pages})

    out = m.api_align_ref_summary(book="vol01", pages="cells:1:1:1")
    assert out["pages"] == [1]

    with pytest.raises(HTTPException) as exc_info:
        m.api_align_ref_summary(book="vol01", pages="cells:not-a-coordinate")
    assert exc_info.value.status_code == 400


def test_ocr_candidates_summary_route_accepts_list(tmp_path, monkeypatch):
    from open_guji_cv.console.routers import products as m

    bk = make_book("vol01")
    monkeypatch.setattr(m, "load_book", lambda book: bk)
    monkeypatch.setattr("open_guji_cv.steps.ocr_candidates.ocr_candidates_summary",
                        lambda book, pages, store: {"pages": pages})

    _write_list(tmp_path, monkeypatch, "mylist", ["vol01:4:1:1"])
    out = m.api_ocr_candidates_summary(book="vol01", pages="list:mylist")
    assert out["pages"] == [4]


# ── runs ─────────────────────────────────────────────────────────────────
def test_runs_status_accepts_cells_and_list(tmp_path, monkeypatch):
    from open_guji_cv.console.routers import runs as m

    bk = make_book("vol01", pages=[1, 2, 3, 4, 5])

    class FakeEngine:
        def __init__(self, book, pipeline, params=None, log=None):
            self.book = book
            self.pipeline = pipeline

        def status(self, pages):
            return {"pages": pages}

    monkeypatch.setattr(m, "load_book", lambda book: bk)
    monkeypatch.setattr(m, "load_pipeline", lambda name: object())
    monkeypatch.setattr(m, "Engine", FakeEngine)

    out = m.api_status(book="vol01", pages="cells:1:1:1,3:1:1")
    assert out["pages"] == [1, 3]

    _write_list(tmp_path, monkeypatch, "mylist", ["vol01:2:1:1"])
    out2 = m.api_status(book="vol01", pages="list:mylist")
    assert out2["pages"] == [2]


def test_runs_status_bad_cells_is_400_not_500(monkeypatch):
    from open_guji_cv.console.routers import runs as m

    bk = make_book("vol01", pages=[1, 2, 3])

    class FakeEngine:
        def __init__(self, book, pipeline, params=None, log=None):
            self.book = book
            self.pipeline = pipeline

        def status(self, pages):
            return {"pages": pages}

    monkeypatch.setattr(m, "load_book", lambda book: bk)
    monkeypatch.setattr(m, "load_pipeline", lambda name: object())
    monkeypatch.setattr(m, "Engine", FakeEngine)

    with pytest.raises(HTTPException) as exc_info:
        m.api_status(book="vol01", pages="cells:not-a-coordinate")
    assert exc_info.value.status_code == 400
