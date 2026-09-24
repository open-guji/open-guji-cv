# -*- coding: utf-8 -*-
"""Step8 复核裁决的三个消费者（2026-09-22）。

钉住的核心是**副作用边界**：三条都不入字形库、不失效产物——那一格的字没变，
Step7 早已入过库。只有「证人对」要改字，而它复用 Step7 的 confirm 通道。
"""
from __future__ import annotations

import io

import pytest

from open_guji_cv.feedback.collate_consumers import (char_convention, collate_ok,
                                                     variant_deny)
from open_guji_cv.feedback.events import EventTarget, make_event


def _ev(kind, payload, key="bxgb:3:2:10", book="bxgb", seq=1):
    return make_event("b", seq, kind,
                      EventTarget(step="step8_collate", unit="cell", key=key,
                                  book=book, page=3),
                      payload, source_format="server")


def _pairs(*evs):
    return [(e, None) for e in evs]


def test_collate_ok_only_books_it():
    res = collate_ok(_pairs(_ev("collate_ok", {})))
    assert res.added == 1 and not res.errors


def test_collate_ok_needs_a_key():
    res = collate_ok(_pairs(_ev("collate_ok", {}, key="")))
    assert res.added == 0 and res.skipped == 1 and res.errors


def test_variant_deny_appends(tmp_path):
    p = tmp_path / "deny.tsv"
    res = variant_deny(_pairs(_ev("variant_deny", {"pair": ["治", "冶"]})),
                       deny_path=str(p))
    assert res.added == 1
    body = p.read_text(encoding="utf-8")
    assert "治\t冶\t" in body and body.startswith("#"), "要有表头说明来历"


def test_variant_deny_is_idempotent(tmp_path):
    p = tmp_path / "deny.tsv"
    ev = lambda s: _ev("variant_deny", {"pair": ["治", "冶"]}, seq=s)  # noqa: E731
    variant_deny(_pairs(ev(1)), deny_path=str(p))
    res = variant_deny(_pairs(ev(2)), deny_path=str(p))
    assert res.added == 0 and res.skipped == 1
    assert p.read_text(encoding="utf-8").count("治\t冶") == 1


def test_variant_deny_reports_bad_payload(tmp_path):
    res = variant_deny(_pairs(_ev("variant_deny", {})), deny_path=str(tmp_path / "d.tsv"))
    assert res.added == 0 and res.skipped == 1 and res.errors


def _book_yaml(tmp_path, body: str):
    p = tmp_path / "bxgb.yaml"
    io.open(p, "w", encoding="utf-8", newline="\n").write(body)
    return p


def test_char_convention_appends_to_book_yaml(tmp_path):
    p = _book_yaml(tmp_path, "id: bxgb\npages: ['3-56']\n")
    res = char_convention(_pairs(_ev("char_convention",
                                     {"pair": ["完", "元"], "kind": "人名",
                                      "note": "女真姓氏"})), book_path=str(p))
    assert res.added == 1
    import yaml
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert doc["char_conventions"][0]["pair"] == ["完", "元"]
    assert doc["char_conventions"][0]["kind"] == "人名"
    assert doc["pages"] == ["3-56"], "其余字段不能被改写"


def test_char_convention_keeps_existing_comments(tmp_path):
    """册 yaml 里有大量带注释的调参记录——全量 safe_dump 会把它们抹掉。"""
    p = _book_yaml(tmp_path, "id: bxgb\n# 2026-09-17 阈值从 0.85 改 0.95，因为换了 r5\nfont:\n  base: x\n")
    char_convention(_pairs(_ev("char_convention", {"pair": ["甫", "父"], "kind": "通假"})),
                    book_path=str(p))
    txt = p.read_text(encoding="utf-8")
    assert "# 2026-09-17 阈值从 0.85 改 0.95" in txt, "注释被 safe_dump 抹掉了"
    assert "char_conventions:" in txt


def test_char_convention_is_idempotent(tmp_path):
    p = _book_yaml(tmp_path, "id: bxgb\n")
    ev = lambda s: _ev("char_convention", {"pair": ["完", "元"], "kind": "人名"}, seq=s)  # noqa: E731
    char_convention(_pairs(ev(1)), book_path=str(p))
    res = char_convention(_pairs(ev(2)), book_path=str(p))
    assert res.added == 0 and res.skipped == 1
    import yaml
    assert len(yaml.safe_load(p.read_text(encoding="utf-8"))["char_conventions"]) == 1


@pytest.mark.parametrize("payload", [{}, {"pair": ["完"]}, {"pair": ["完", "元"]}])
def test_char_convention_reports_bad_payload(tmp_path, payload):
    p = _book_yaml(tmp_path, "id: bxgb\n")
    res = char_convention(_pairs(_ev("char_convention", payload)), book_path=str(p))
    assert res.added == 0 and res.skipped == 1 and res.errors


def test_unmark_jiajie_only_drops_this_books_rows(tmp_path):
    """撤通假只删**本书复核批次**标的那行；别的书标的、别的字对都不动。"""
    from open_guji_cv.feedback.collate_consumers import unmark_jiajie
    p = tmp_path / "jiajie.tsv"
    p.write_text("# 头\n甫\t父\thuman:evt_bxgb-collate_000001\n"
                 "甫\t父\thuman:evt_other-collate_000009\n"
                 "早\t蚤\thuman:evt_bxgb-collate_000002\n", encoding="utf-8")
    res = unmark_jiajie(_pairs(_ev("unmark_jiajie", {"pair": ["甫", "父"], "book": "bxgb"})),
                        path=str(p))
    assert res.added == 1 and not res.errors
    assert p.read_text(encoding="utf-8") == ("# 头\n甫\t父\thuman:evt_other-collate_000009\n"
                                             "早\t蚤\thuman:evt_bxgb-collate_000002\n")


def test_collate_verdict_only_books_it():
    from open_guji_cv.feedback.collate_consumers import collate_verdict
    res = collate_verdict(_pairs(_ev("collate_verdict", {"pair": ["甲", "乙"], "who": "ours"})))
    assert res.consumer == "collate_verdict" and res.added == 1


def _log_with(tmp_path, *kinds_pairs):
    from open_guji_cv.feedback.events import EventLog
    log = EventLog(tmp_path / "fb")
    log.append([make_event("bxgb-collate", i + 1, k,
                           EventTarget(step="step8_collate", unit="cell", key="bxgb:3:2:10",
                                       book="bxgb"),
                           {"pair": list(p), "book": "bxgb"}, source_format="server")
                for i, (k, p) in enumerate(kinds_pairs)])
    return log


def test_backlog_mark_unmark_mark_ends_marked(tmp_path):
    """积压的「标 → 撤 → 再标」一起消费：按日志里最后一次（标）办，表里要有这一对。"""
    from open_guji_cv.feedback.collate_consumers import mark_jiajie, unmark_jiajie
    P = ("甫", "父")
    log = _log_with(tmp_path, ("mark_jiajie", P), ("unmark_jiajie", P), ("mark_jiajie", P))
    p = tmp_path / "jiajie.tsv"
    evs = log.read("bxgb-collate")
    mark_jiajie(_pairs(*[e for e in evs if e.kind == "mark_jiajie"]), path=str(p), log=log)
    unmark_jiajie(_pairs(*[e for e in evs if e.kind == "unmark_jiajie"]), path=str(p), log=log)
    assert "甫\t父" in p.read_text(encoding="utf-8")


def test_backlog_mark_unmark_ends_unmarked(tmp_path):
    """最后一次是撤：mark 那条就别加（加了也会被撤，但别让中间态落盘）。"""
    from open_guji_cv.feedback.collate_consumers import mark_jiajie, unmark_jiajie
    P = ("甫", "父")
    log = _log_with(tmp_path, ("mark_jiajie", P), ("unmark_jiajie", P))
    p = tmp_path / "jiajie.tsv"
    evs = log.read("bxgb-collate")
    res = mark_jiajie(_pairs(*[e for e in evs if e.kind == "mark_jiajie"]), path=str(p), log=log)
    assert res.added == 0
    unmark_jiajie(_pairs(*[e for e in evs if e.kind == "unmark_jiajie"]), path=str(p), log=log)
    assert not p.exists() or "甫\t父" not in p.read_text(encoding="utf-8")
