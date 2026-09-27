# -*- coding: utf-8 -*-
"""字位流 join · 單行小注（bxgb 版式）从 Step3 到 9.1 的一条线。

Step3 1.11 起單行小注自成 `kind="jiazhu_solo"`、`sub=None`（`row_boundaries.CELL_KINDS`），
与 Step7 按「一个字」记的 `sub=None` 直接按 `(slot, "")` 对上，9.1 出不带 `|` 的 `<注>`。

1.10 及以前它借 `jiazhu_a` 的壳存（`sub='a'`），join 查空 → 78 条假 stale，文案还写着
"多半是产物过期"，照着去重跑 Step7 一条不少，白费一轮（2026-09-19 bxgb 实测）。
`_lookup_cell` 里那段回查是给旧产物留的过渡兜底，bxgb 从 Step3 重跑后可删，
这里的 legacy 测试到时一起删。

这里守三件事：
1. 新记法：`jiazhu_solo` 直接命中，kind 带到 SlotRec，9.1 出 `<…>`；
2. 旧记法兜底：只有 a 半 + Step7 无 sub 才认，**真双行夹注缺半边仍要报 stale**；
3. 渲染：連續單行注并成一条 `<…>`，excluded 跳过、阙文 `[[]]`，整段排除不留 `<>`。
"""

from __future__ import annotations

from open_guji_cv.products.kinds.cells import CellRec
from open_guji_cv.products.kinds.recog import AdmitRec
from open_guji_cv.render.guji_markdown import render_column
from open_guji_cv.report.slots import SlotRec, _lookup_cell, _to_slot


def _cell(slot: int, sub: str | None, kind: str) -> CellRec:
    return CellRec(slot=slot, pos=slot, y0=0, y1=0, x0=0, x1=0,
                   kind=kind, sub=sub, order=slot)


def _admit(slot: int, sub: str | None, char: str | None, admit: bool = True,
           doubts: list[str] | None = None) -> AdmitRec:
    return AdmitRec(id="", slot=slot, sub=sub, admit=admit, char=char,
                    doubts=doubts or [])


# ── 1. 新记法 ──────────────────────────────────────────────────

def test_solo_note_kind_matches_directly_and_carries_kind():
    by_key = {(17, ""): _cell(17, None, "jiazhu_solo")}
    cell = _lookup_cell(by_key, _admit(17, None, "憲"))
    assert cell is not None and cell.kind == "jiazhu_solo"
    rec = _to_slot("bxgb", 8, 1, _admit(17, None, "憲"), cell)
    assert rec.kind == "jiazhu_solo" and rec.sub is None and rec.is_text


# ── 2. 旧记法兜底（过渡） ────────────────────────────────────────

def test_legacy_solo_note_stored_as_lone_jiazhu_a_is_recovered():
    """Step3 ≤1.10 的产物：只有 `(17,'a')`、没有 b；Step7 记 `sub=None`。"""
    by_key = {(17, "a"): _cell(17, "a", "jiazhu_a")}
    cell = _lookup_cell(by_key, _admit(17, None, "憲"))
    assert cell is not None, "旧记法的單行小注应认回来，不该报 stale"
    assert cell.kind == "jiazhu_a"


def test_paired_jiazhu_missing_half_still_stale():
    """Step3 两半都在（真双行夹注），Step7 却记了 `sub=None`——真对不上，必须继续报。"""
    by_key = {(4, "a"): _cell(4, "a", "jiazhu_a"),
              (4, "b"): _cell(4, "b", "jiazhu_b")}
    assert _lookup_cell(by_key, _admit(4, None, "張")) is None


def test_normal_body_char_unaffected():
    by_key = {(2, ""): _cell(2, None, "char")}
    cell = _lookup_cell(by_key, _admit(2, None, "次"))
    assert cell is not None and cell.kind == "char"


def test_admit_rec_with_sub_does_not_fall_back():
    """Step7 自己带了 `sub`，就按它查——别拿 `'a'` 去兜 `'b'`。"""
    by_key = {(5, "a"): _cell(5, "a", "jiazhu_a")}
    assert _lookup_cell(by_key, _admit(5, "b", "溫")) is None


def test_slot_absent_entirely_is_stale():
    assert _lookup_cell({(1, ""): _cell(1, None, "char")}, _admit(9, None, "某")) is None


# ── 3. 渲染 ─────────────────────────────────────────────────────

def _slot(slot: int, kind: str, char: str | None, *, excluded=False, unreadable=False) -> SlotRec:
    return SlotRec(id="", page=8, col=1, slot=slot, sub=None, kind=kind, char=char,
                   admit=char is not None, channel=None,
                   excluded=excluded, unreadable=unreadable, human=False)


def test_render_groups_consecutive_solo_notes_without_bar():
    slots = [_slot(16, "char", "生"), _slot(17, "jiazhu_solo", "憲"),
             _slot(18, "jiazhu_solo", "平"), _slot(19, "char", "閭")]
    assert render_column(slots, n_raised=0, n_lead_blank=0) == "生:jz[憲平]{type=单行}閭"


def test_render_solo_note_separated_by_body_char_stays_two_notes():
    slots = [_slot(5, "jiazhu_solo", "德"), _slot(6, "jiazhu_solo", "潤"),
             _slot(7, "char", "葉"), _slot(8, "jiazhu_solo", "翥")]
    assert render_column(slots, n_raised=0, n_lead_blank=0) == ":jz[德潤]{type=单行}葉:jz[翥]{type=单行}"


def test_render_solo_note_excluded_and_unreadable():
    slots = [_slot(1, "jiazhu_solo", "憲"),
             _slot(2, "jiazhu_solo", None, excluded=True),
             _slot(3, "jiazhu_solo", None, unreadable=True)]
    assert render_column(slots, n_raised=0, n_lead_blank=0) == ":jz[憲□]{type=单行}"
    only_excluded = [_slot(1, "jiazhu_solo", None, excluded=True)]
    assert render_column(only_excluded, n_raised=0, n_lead_blank=0) == ""
