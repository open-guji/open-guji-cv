# -*- coding: utf-8 -*-
"""对勘的两道防线（2026-09-27，CV 总管追加）：

1. `report/run.py::collate_book` 单页崩溃不拖垮整册——`collate_page` 抛异常
   时记进 `page_errors`，跳过这一页，继续跑剩下的页。
2. `report/collate.py::diff_page` 入口挡坏数据——字位 `char`/`guess` 长度
   不是 1 的（真实案例：vol01 一批人裁事件 UTF-8 误当 cp1252 解码，一个字位
   存成 3 个 code point 的假"字"）按阙文处理，不让下标错位越界崩溃。

两条根因都在别处（`collate_page` 之外的异常、上游数据乱码），这里只测
「挡不挡得住」，不测「怎么修根因」——根因分别是另一个 bug（page_errors）
和 H 道要修的上游数据（乱码本身）。
"""
from __future__ import annotations

from dataclasses import replace

from open_guji_cv.clustering.align_eval import build_ngram_index
from open_guji_cv.report.collate import PLACEHOLDER, _sanitize_slots, diff_page
from open_guji_cv.report.run import collate_book
from open_guji_cv.report.slots import SlotRec
from open_guji_cv.report.witness import Witness

TRUTH = "皇帝二年秋七月甲子詔曰朕承天命撫馭萬方今澤及蒼生宜加恩賚布告天下咸使聞知"


def _slot(i: int, char: str | None, *, admit: bool = True, guess: str | None = None,
         book: str = "vol01", page: int = 24, col: int = 7) -> SlotRec:
    return SlotRec(id=f"{book}:{page}:{col}:{i}", page=page, col=col, slot=i, sub=None,
                  kind="char", char=char, admit=admit, channel=("human" if admit else None),
                  excluded=False, unreadable=False, human=admit, guess=guess)


def _witness(text: str = TRUTH) -> Witness:
    return Witness(name="w", label="w", quality="best", text=text,
                  index=build_ngram_index(text), text_norm=text)


# ── 1. collate_book 单页崩溃不拖垮整册 ──────────────────────────────

def test_collate_book_skips_the_crashing_page_and_keeps_the_rest(monkeypatch):
    from open_guji_cv.report.collate import PageResult

    def fake_collate_page(store, book, page, witnesses, stale):
        if page == 2:
            raise IndexError("list index out of range")
        return {w.label: PageResult(page=page, anchored=True, n_equal=3) for w in witnesses}

    monkeypatch.setattr("open_guji_cv.report.run.collate_page", fake_collate_page)
    w = _witness()
    doc = collate_book("tbook", [1, 2, 3], [w])

    assert [pe["page"] for pe in doc["page_errors"]] == [2]
    assert doc["page_errors"][0]["error_type"] == "IndexError"
    assert "list index out of range" in doc["page_errors"][0]["message"]
    assert [rec["page"] for rec in doc["page_stats"]] == [1, 3], "崩溃页跳过，其余页照样出结果"
    assert doc["summary"]["n_page_errors"] == 1


def test_collate_book_with_no_crashes_reports_zero_page_errors(monkeypatch):
    from open_guji_cv.report.collate import PageResult

    def fake_collate_page(store, book, page, witnesses, stale):
        return {w.label: PageResult(page=page, anchored=True, n_equal=1) for w in witnesses}

    monkeypatch.setattr("open_guji_cv.report.run.collate_page", fake_collate_page)
    w = _witness()
    doc = collate_book("tbook", [1, 2], [w])
    assert doc["page_errors"] == []
    assert doc["summary"]["n_page_errors"] == 0


# ── 2. diff_page 挡坏数据（长度≠1 的假字） ──────────────────────────

def test_sanitize_slots_neutralizes_multi_codepoint_char():
    """乱码真实案例：`'å†…'` 是 3 个 code point，应为 1 个字「内」。"""
    bad = _slot(16, "å†…", admit=True)
    good = _slot(17, "内", admit=True)
    out, warnings = _sanitize_slots([good, bad])
    assert out[0].char == "内"
    assert out[1].char is None and out[1].unreadable
    assert len(warnings) == 1 and "vol01:24:7:16" in warnings[0]


def test_sanitize_slots_leaves_none_and_placeholder_alone():
    """`char=None`（正常阙文）与占位符 `□`（长度 1）都不该被当成坏数据。"""
    none_slot = _slot(1, None, admit=False)
    placeholder_slot = _slot(2, PLACEHOLDER, admit=True)
    out, warnings = _sanitize_slots([none_slot, placeholder_slot])
    assert out[0].char is None and out[1].char == PLACEHOLDER
    assert warnings == []


def test_sanitize_slots_only_drops_bad_guess_without_touching_char():
    """只有 `guess` 长度异常时，字形层的 `char` 不该被牵连。"""
    s = replace(_slot(3, "澤", admit=True), guess="å†…")
    out, warnings = _sanitize_slots([s])
    assert out[0].char == "澤" and out[0].guess is None and not out[0].unreadable
    assert len(warnings) == 1


def test_diff_page_does_not_crash_on_mojibake_slot_and_marks_it_unreadable():
    """端到端复现 vol01 p24：一个 3-code-point 假字混进整页，`diff_page` 不
    该 IndexError（旧版会，因为串长度跟字位数对不上），且这一位要出
    `unreadable`，其余位置照常对齐、不因这一位错位。"""
    w = _witness()
    slots = []
    for i, ch in enumerate(TRUTH):
        i1 = i + 1
        if ch == "澤":
            # 复现坏数据：这一位的 char 是 3-code-point 的假字，不是 1 个字。
            slots.append(_slot(i1, "å†…", admit=True))
        else:
            slots.append(_slot(i1, ch, admit=True))

    res = diff_page(slots, w, page=24)   # 不抛异常即算通过第一关

    assert res.anchored, res.note
    assert len(res.warnings) == 1 and "å†…" in res.warnings[0]
    bad_diffs = [d for d in res.diffs if d.kind == "unreadable"]
    assert len(bad_diffs) == 1 and bad_diffs[0].char == PLACEHOLDER
    # 其余位置没有被这一位的长度问题带偏——同一批「澤」在别处都应保持一致，
    # 这里只有这一格出问题，说明没有连锁错位。
    assert not any(d.kind in ("sub.confusable", "sub.other") for d in res.diffs)
