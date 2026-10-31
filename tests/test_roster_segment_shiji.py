# -*- coding: utf-8 -*-
"""史記（写本）职名页自己的实现 `books/shiji_wyg/roster_segment`：写本「臣」斜贴邻字的拆分，
以及 Step3 壳按册的套书选它（殿本册仍用殿本的）。合成数据，不读真书。"""

from __future__ import annotations

import open_guji_cv.steps  # noqa: F401  —— 注册 Step / 产物种类
from helpers import make_book, run_keben_chain
from open_guji_cv.books.shiji_wyg import roster_segment as SJ
from test_roster_segment import W, _roster_column, _xieben_column


def test_shiji_splits_stuck_chen_by_page_chen_row():
    cols = [(_roster_column()[0], (10.0, W - 10.0)) for _ in range(2)]
    cols.append((_xieben_column(1620), (10.0, W - 10.0)))
    rc = SJ.segment_roster_page(cols)[2]
    assert len(rc.items) == 6 and rc.items[3].y0 == 1620


def _run(tmp_path, monkeypatch, **bk):
    book = make_book(expected_cols=4, chars_per_line=21, params={"row_segment": {"roster_pages": ["1"]}}, **bk)
    return run_keben_chain(tmp_path, monkeypatch, book=book, through="row_segment", h=2000,
                           n_cols=4, w=500, period=100, col_n_chars={4: 3, 3: 7, 2: 12, 1: 5})


def test_step_uses_shiji_module_only_for_shiji_books(tmp_path, monkeypatch):
    calls = []
    real = SJ.segment_roster_page
    monkeypatch.setattr(SJ, "segment_roster_page", lambda *a, **k: calls.append(1) or real(*a, **k))
    _run(tmp_path / "dian", monkeypatch)
    assert not calls                                   # 殿本册走殿本的实现
    _run(tmp_path / "sj", monkeypatch, seg_set="shiji_wyg")
    assert calls                                       # 史記册走 books/shiji_wyg 的
