# -*- coding: utf-8 -*-
"""未放行格不该被对勘当成认错字（任务书 P-对勘未放行格口径）。

根因链见 overview 仓 `Step5-字符识别/inbox/R-形近溯源/20260927-1636-done.md`：
`seed_admit._pick_char()` 在 `admit=False` 时也把 Step5-a 候选首选写进
`AdmitRec.char`（供人审卡看「AI 猜测」），`report/slots.py::_to_slot` 原样把它
搬进 `SlotRec.char`，于是「待审格的未采纳猜测」被 9.3 对勘当成了「认错字」
（`sub.confusable`/`sub.other`）。vol03 五格全部 `admit=False`，真实案例即
澤/擇 一族（T3 形近对）——本文件用同一对字复现。
"""
from __future__ import annotations

from open_guji_cv.clustering.align_eval import build_ngram_index
from open_guji_cv.products.kinds.recog import AdmitRec
from open_guji_cv.report.collate import PLACEHOLDER, _anchor_char, _slot_char, diff_page
from open_guji_cv.report.slots import _to_slot
from open_guji_cv.report.witness import Witness

TRUTH = "皇帝二年秋七月甲子詔曰朕承天命撫馭萬方今澤及蒼生宜加恩賚布告天下咸使聞知"


def _rec(slot: int, *, admit: bool, char: str | None, channel: str | None = None,
        doubts: list[str] | None = None, evidence: dict | None = None) -> AdmitRec:
    return AdmitRec(id=f"vol03:21:7:{slot}", slot=slot, sub=None, admit=admit,
                    char=char, channel=channel, doubts=doubts or [],
                    evidence=evidence or {})


def test_unadmitted_normal_slot_char_is_none_guess_keeps_ai_pick():
    """未放行、不在排除名单：char 清空成阙文，AI 猜测挪进 guess，不当成定论。"""
    rec = _rec(9, admit=False, char="擇", doubts=["margin_low(0.30)"])
    s = _to_slot("vol03", 21, 7, rec, None)
    assert s.char is None
    assert s.guess == "擇"
    assert s.unreadable
    assert not s.admit


def test_admitted_slot_char_unchanged():
    rec = _rec(1, admit=True, char="澤", channel="dual")
    s = _to_slot("vol03", 21, 7, rec, None)
    assert s.char == "澤" and not s.unreadable


def test_human_reviewed_slot_char_unchanged():
    """人裁格照常出字（seed_admit 里 channel=human 恒 admit=True）。"""
    rec = _rec(12, admit=True, char="澤", channel="human")
    s = _to_slot("vol03", 21, 7, rec, None)
    assert s.char == "澤" and s.human and not s.unreadable


def test_defect_damaged_slot_untouched_by_the_fix():
    """排除名单（damaged）不受这条口径影响——那是 Step7 自己给的占位，
    `guess` 已经是人给的「最像哪个字」，不能被这里的猜测逻辑覆盖。"""
    rec = _rec(6, admit=False, char="□", doubts=["excluded"],
               evidence={"excluded": "human:damaged", "damaged": True, "guess": "塊"})
    s = _to_slot("bxgb", 27, 8, rec, None)
    assert s.char == "□" and s.guess == "塊" and s.defect and not s.unreadable


def test_slot_char_and_anchor_char_split():
    """`_slot_char` 出差异用（不退猜测）；`_anchor_char` 锚定用（容忍猜测）。"""
    rec = _rec(9, admit=False, char="擇")
    s = _to_slot("vol03", 21, 7, rec, None)
    assert _slot_char(s) == PLACEHOLDER
    assert _anchor_char(s) == "擇"


def _witness(text: str) -> Witness:
    return Witness(name="w", label="w", quality="best", text=text,
                  index=build_ngram_index(text), text_norm=text)


def _slots_with_one_swap(swap_char: str, swap_from: str, *, admit: bool,
                         channel: str | None) -> list:
    """按 `TRUTH` 造一页字位流，`swap_from` 那个字替换成 `swap_char`
    （放行状态与通道可控），其余字都放行、都对。"""
    out = []
    for i, ch in enumerate(TRUTH):
        slot = i + 1
        if ch == swap_from:
            rec = _rec(slot, admit=admit, char=swap_char, channel=channel,
                       doubts=[] if admit else ["margin_low(0.30)"])
        else:
            rec = _rec(slot, admit=True, char=ch, channel="dual")
        out.append(_to_slot("vol03", 21, 7, rec, None))
    return out


def test_diff_page_does_not_count_unadmitted_slot_as_confusable():
    """R 单里那 5 格的复现：未放行位的 AI 猜测与整理本形近（澤/擇），
    修复前会被记成 sub.confusable，修复后应记成 unreadable，且不影响锚定。"""
    w = _witness(TRUTH)
    slots = _slots_with_one_swap("擇", "澤", admit=False, channel=None)

    res = diff_page(slots, w, page=21)
    assert res.anchored, res.note

    kinds = {d.kind for d in res.diffs}
    assert "sub.confusable" not in kinds and "sub.other" not in kinds

    unread = [d for d in res.diffs if d.kind == "unreadable"]
    assert len(unread) == 1
    assert unread[0].char == PLACEHOLDER
    assert not unread[0].admit


def test_diff_page_still_flags_human_reviewed_mismatch():
    """人裁格照常出字：人裁定的字跟整理本不一致时仍要正常出现在差异里，
    不能被「未放行不出字」这条口径误伤（人裁 admit 恒 True）。"""
    w = _witness(TRUTH)
    slots = _slots_with_one_swap("擇", "澤", admit=True, channel="human")

    res = diff_page(slots, w, page=21)
    assert res.anchored, res.note

    hits = [d for d in res.diffs if d.human]
    assert len(hits) == 1
    assert hits[0].kind == "sub.confusable"
    assert hits[0].char == "擇"
