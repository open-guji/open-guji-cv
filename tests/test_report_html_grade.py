# -*- coding: utf-8 -*-
"""`report/html.py`：分层分区渲染 ＋ 截条图 ＋ 离线深链退到静态图（2026-09-27）。

只测 `render()` 吃一份手造的 `doc`（`collate_book()` 的输出形状）产出什么 HTML——
不碰 ProductStore/RunContext，那是 `test_report_strips.py` 的事。
"""
from __future__ import annotations

from open_guji_cv.report.html import render

WITNESS = "证人甲"


def _doc(diffs: list[dict], *, grade_counts=None, n_settled=0, n_todo=0) -> dict:
    return {
        "book": "tbook", "built_at": "2026-09-27 00:00", "elapsed_s": 1.0, "pages": [1],
        "witnesses": [{"name": WITNESS, "label": WITNESS, "quality": "best",
                       "line_is_column": False, "n_chars": 100}],
        "unanchored": {WITNESS: []}, "stale": [],
        "summary": {"by_witness": {WITNESS: {
            "quality": "best", "n_equal": 10, "counts": {}, "by_kind_channel": {},
            "variant_pairs": [], "human_disagree": [], "cols": {},
            "grade_counts": grade_counts or {}, "n_settled": n_settled, "n_todo": n_todo,
            "misanchored_pages": [],
        }}},
        "page_stats": [], "cols": [], "diffs": diffs,
    }


def _sub_diff(**kw) -> dict:
    d = {"id": "tbook:1:1:1", "page": 1, "col": 1, "slot": 1, "sub": None,
        "kind": "sub.other", "char": "甲", "ref": "乙", "witness": WITNESS,
        "channel": None, "admit": False, "human": False, "n": 1,
        "hyp_ctx": "x甲y", "ref_ctx": "x乙y", "grade": "suspect", "strip": None}
    d.update(kw)
    return d


def test_suspect_section_is_open_by_default():
    html = render(_doc([_sub_diff(grade="suspect")]), console="")
    assert '<details id="g-suspect" open>' in html


def test_non_suspect_sections_are_collapsed():
    html = render(_doc([_sub_diff(grade="taboo")]), console="")
    assert '<details id="g-taboo">' in html
    assert '<details id="g-taboo" open>' not in html


def test_gap_kind_renders_without_pair_image_markup():
    """增删（missing/extra）走 `_gap_entry`，不是 `_entry`——不该出现"跳去改"以外的
    图片占位（旧脚本口径：增删只出文字，见 collation_grade 模块头「另计」）。"""
    d = _sub_diff(kind="missing", char="", ref="丙丁", n=2, grade="gap")
    html = render(_doc([d]), console="http://x")
    assert "整理本多出" in html
    assert "丙丁" in html


def test_strip_image_embedded_when_present():
    d = _sub_diff(strip="strips/证人甲/tbook_1_1_1.webp")
    html = render(_doc([d]), console="")
    assert '<img class="strip" src="strips/证人甲/tbook_1_1_1.webp"' in html


def test_no_console_link_falls_back_to_strip_path():
    """离线交付包：`console=""` 时深链退到截图路径本身，不是空链接。"""
    d = _sub_diff(strip="strips/证人甲/tbook_1_1_1.webp")
    html = render(_doc([d]), console="")
    assert "strips/证人甲/tbook_1_1_1.webp" in html
    assert "看大图" in html


def test_no_console_no_strip_yields_no_jump_link():
    d = _sub_diff(strip=None)
    html = render(_doc([d]), console="")
    assert "<a class='jump'" not in html


def test_console_link_points_to_step7_for_char_diffs():
    d = _sub_diff()
    html = render(_doc([d]), console="http://127.0.0.1:8640")
    assert "step/step7/?id=tbook:1:1:1" in html


def test_lede_reports_settled_and_todo_totals():
    html = render(_doc([_sub_diff()], n_settled=3, n_todo=1), console="")
    assert ">3<" in html
    assert ">1<" in html
