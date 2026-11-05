# -*- coding: utf-8 -*-
"""字位流 · 排除名单按理由分两路（2026-09-20 bxgb 对勘查出来的）。

`not_a_char`（非字）才是「这一格本不存在」；`seg_defect`/`damaged` 是「字确实在这儿、
图块不能进库」——字位必须占住，文本层出阙文，否则整列字数对不上、对勘把它们报成
「整理本有刻本无」（bxgb 155 条名单里 131 条 seg_defect，80 条正落在漏字位上）。
"""

from __future__ import annotations

from open_guji_cv.products.kinds.cells import CellRec
from open_guji_cv.products.kinds.recog import AdmitRec
from open_guji_cv.report.slots import _to_slot


def _cell(slot: int) -> CellRec:
    return CellRec(slot=slot, pos=slot, y0=0, y1=0, x0=0, x1=0, kind="char", sub=None, order=slot)


def _excluded(slot: int, note: str | None, char: str | None = None) -> AdmitRec:
    return AdmitRec(id="", slot=slot, sub=None, admit=False, char=char, reading=None,
                    channel=None, doubts=["excluded"],
                    evidence=({"excluded": note} if note is not None else {}))


def _slot(rec: AdmitRec):
    return _to_slot("bxgb", 6, 7, rec, _cell(rec.slot))


def test_seg_defect_is_a_text_slot_rendered_as_lacuna():
    s = _slot(_excluded(20, "human:seg_defect"))
    assert s.defect and not s.excluded and s.is_text and s.unreadable


def test_not_a_char_is_skipped():
    s = _slot(_excluded(20, "human:not_a_char"))
    assert s.excluded and not s.defect and not s.is_text


def test_damaged_keeps_step7_placeholder():
    s = _slot(_excluded(20, "human:damaged", char="□"))
    assert s.defect and not s.excluded and s.is_text and not s.unreadable
    assert s.char == "□"


def test_legacy_record_without_evidence_stays_excluded():
    """Step7 早期产物没有 evidence：按原来的口径当非字，别把老书的输出悄悄改了。"""
    s = _slot(_excluded(20, None))
    assert s.excluded and not s.defect


def _excluded_with_char(slot: int, note: str, hc: str) -> AdmitRec:
    return AdmitRec(id="", slot=slot, sub=None, admit=False, char=None, reading=None,
                    channel=None, doubts=["excluded"],
                    evidence={"excluded": note, "human_char": hc})


def test_not_a_char_ignores_human_char():
    """非字就是非字：即使 evidence 里混进了字，也不占位。"""
    s = _slot(_excluded_with_char(20, "human:not_a_char", "手"))
    assert s.excluded and not s.defect and not s.is_text


def test_seed_admit_attaches_human_char_to_excluded_cell(tmp_path, monkeypatch):
    """overview#403 缺口 B 的 Step7 一端：名单上的 crop_defect 格，事件里人给了字 → 照旧
    不放行、不进库（`admit=False`、`channel=None`），字挂在 `evidence.human_char`；
    没给字的格不带；非字不带。"""
    import json
    from helpers import make_book, make_ctx, page_match, write_product
    import open_guji_cv.steps  # noqa: F401  注册步骤
    from open_guji_cv.core.step import STEPS
    from open_guji_cv.feedback import bindings
    from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
    monkeypatch.setattr(bindings, "book_bindings", lambda *a, **k: {})
    fb = tmp_path / "fb"
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(fb))
    ex = tmp_path / "crop_exclusions.jsonl"
    ex.write_text("".join(json.dumps({"instance_id": f"tbook:1:1:{s}", "reason": r, "origin": o},
                                     ensure_ascii=False) + "\n"
                          for s, r, o in ((1, "crop_defect", "gate"), (2, "crop_defect", "gate"),
                                          (3, "not_a_char", "human"))), encoding="utf-8")
    monkeypatch.setenv("GUJI_EXCLUSIONS", str(ex))
    ctx = make_ctx(tmp_path, make_book("tbook"), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(1, "tbook", col=1, recs=[
        dict(slot=s, verdict="unsure", cov=0.96, wmax=0.0, candidates=[("地", 0.96)]) for s in (1, 2, 3)]))

    def ev(slot, seq):
        return make_event("b", seq, "confirm",
                          EventTarget(step="seed_admit", unit="cell", key=f"tbook:1:1:{slot}", book="tbook",
                                      page=1, col=1, slot=slot),
                          {"v": "confirm", "shape": "手"}, source_format="server")
    EventLog(fb).append([ev(1, 1), ev(3, 2)])
    sa = STEPS["seed_admit"].run_page(ctx, 1)["seed_admit"]
    by = {r.slot: r for cc in sa.columns for r in cc.chars}
    assert all(by[s].admit is False and by[s].channel is None and by[s].doubts == ["excluded"]
               for s in (1, 2, 3))
    assert by[1].evidence.get("human_char") == "手"
    assert "human_char" not in by[2].evidence
    assert "human_char" not in by[3].evidence
    s1 = _to_slot("tbook", 1, 1, by[1], _cell(1))
    assert s1.char == "手" and s1.defect and not s1.unreadable


import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")   # 老测试按「放行开关缺省全关」造的数据，见 conftest
