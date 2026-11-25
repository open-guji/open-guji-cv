# -*- coding: utf-8 -*-
"""`feedback.lookup.human_chars`：事件侧的人裁定字，勾了「字形不入库」也算定了字（2026-09-20）。

bxgb 11 个「已裁未放行」里 5 个是人定了字但勾了不入库——Step7 只从字形库拿人裁，
这 5 个永远未放行、文本层出阙文、定字台又不再出卡，两边都不管。
"""
from __future__ import annotations

from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
from open_guji_cv.feedback.lookup import human_chars


def _ev(key: str, payload: dict, seq: int, batch: str = "b"):
    _, pg, col, slot = key.split(":")
    return make_event(batch, seq, "confirm",
                      EventTarget(step="seed_admit", unit="cell", key=key, book="vol01",
                                  page=int(pg), col=int(col), slot=int(slot)),
                      payload, source_format="server")


def test_no_glyph_lib_confirm_still_counts(tmp_path):
    log = EventLog(tmp_path)
    log.append([_ev("vol01:4:1:3", {"v": "confirm", "shape": "太", "reading": "太", "no_glyph_lib": True}, 1)])
    assert human_chars("vol01", log) == {"vol01:4:1:3": "太"}


def test_last_verdict_wins_and_other_kinds_ignored(tmp_path):
    log = EventLog(tmp_path)
    log.append([_ev("vol01:4:1:3", {"v": "confirm", "shape": "大"}, 1),
                _ev("vol01:4:1:3", {"v": "confirm", "shape": "太"}, 2),
                _ev("vol01:4:1:4", {"v": "seg_defect", "quality": "truncated"}, 3),
                _ev("vol01:4:1:5", {"v": "not_a_char"}, 4),
                _ev("vol02:1:1:1", {"v": "confirm", "shape": "他"}, 5)])
    got = human_chars("vol01", log)
    assert got == {"vol01:4:1:3": "太"}, "后到覆盖；seg_defect / not_a_char / 别的书不算"


def test_later_step8_fix_beats_earlier_step7_by_time(tmp_path):
    """按时间后到覆盖，不按批次名：`bxgb-list-…` 排在 `bxgb-collate` 后面，
    按批次名排会把 Step8 复核改好的字盖回 Step7 的旧字（2026-09-24）。"""
    from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
    log = EventLog(tmp_path)
    t = EventTarget(step="x", unit="cell", key="bxgb:3:1:1", book="bxgb")
    log.append([make_event("bxgb-list-lu-decide", 1, "confirm", t,
                           {"v": "confirm", "shape": "甲"}, ts="2026-09-20T00:00:00Z"),
                make_event("bxgb-collate", 1, "confirm", t,
                           {"v": "confirm", "shape": "乙"}, ts="2026-09-24T00:00:00Z")])
    assert human_chars("bxgb", log)["bxgb:3:1:1"][0] == "乙"


def test_stale_mark_voids_earlier_verdicts_only(tmp_path):
    """库里撤下（human_stale_<日期>）的位：那天及以前的事件作废，之后再裁的照常生效（2026-09-25）。"""
    log = EventLog(tmp_path)
    old = _ev("vol01:4:1:3", {"v": "confirm", "shape": "目"}, 1)
    old.ts = "2026-09-10T05:00:00Z"
    log.append([old])
    assert human_chars("vol01", log, stale={"vol01:4:1:3": "20260925"}) == {}
    new = _ev("vol01:4:1:3", {"v": "confirm", "shape": "文"}, 2)
    new.ts = "2026-09-26T01:00:00Z"
    log.append([new])
    assert human_chars("vol01", log, stale={"vol01:4:1:3": "20260925"}) == {"vol01:4:1:3": "文"}


def test_stale_mark_minute_precision_same_day(tmp_path):
    log = EventLog(tmp_path)
    a = _ev("vol01:4:1:3", {"v": "confirm", "shape": "目"}, 1); a.ts = "2026-09-25T06:00:00Z"
    b = _ev("vol01:4:1:3", {"v": "confirm", "shape": "文"}, 2); b.ts = "2026-09-25T08:00:00Z"
    log.append([a, b])
    assert human_chars("vol01", log, stale={"vol01:4:1:3": "20260925T0700"}) == {"vol01:4:1:3": "文"}


def test_missing_events_dir_raises(tmp_path, monkeypatch):
    """读工作区事件日志、目录却不存在 → 报错，不当「没人裁过」（2026-10-25，殿本 vol06/10 没设 GUJI_WORKSPACE）。"""
    import pytest
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path / "nowhere"))
    monkeypatch.delenv("GUJI_ALLOW_NO_EVENTS", raising=False)
    with pytest.raises(FileNotFoundError, match="GUJI_WORKSPACE"):
        human_chars("vol01", stale={})
    monkeypatch.setenv("GUJI_ALLOW_NO_EVENTS", "1")
    assert human_chars("vol01", stale={}) == {}


def test_unbound_for_missing_patch_raises(tmp_path, monkeypatch):
    """绑定行 `why=no_patch`（有当时的图、现格字块图拿不到）→ 报错，不悄悄当绑丢（2026-10-25，vol10 丢 68/146）。"""
    import pytest

    import open_guji_cv.feedback.bindings as B
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path))
    ev = _ev("vol01:4:1:3", {"v": "confirm", "shape": "太"}, 1)
    EventLog(tmp_path).append([ev])
    row = {"event": ev.id, "key": ev.target.key, "status": "unanchored", "bound": None, "why": "no_patch"}
    monkeypatch.setattr(B, "book_bindings", lambda book, log=None: {ev.id: row})
    monkeypatch.delenv("GUJI_ALLOW_LOST_HUMAN", raising=False)
    # 2026-11-10 起：上限内默认放行；超过上限才拦
    lost0 = {}
    assert human_chars("vol01", stale={}, lost=lost0) == {}
    monkeypatch.setattr("open_guji_cv.feedback.lookup.LOST_HUMAN_DEFAULT_MAX", 0)
    with pytest.raises(RuntimeError, match="字块图"):
        human_chars("vol01", stale={})
    monkeypatch.setenv("GUJI_ALLOW_LOST_HUMAN", "1")
    lost = {}
    assert human_chars("vol01", stale={}, lost=lost) == {} and "vol01:4:1:3" in lost


def test_stale_tsv_read_even_when_glyph_db_unreadable(tmp_path, monkeypatch):
    """字形库读不到时，作废表 stale_verdicts.tsv 照样生效（以前 except 里直接 return，tsv 被整张忽略）。"""
    from open_guji_cv.feedback.lookup import stale_human_marks
    fb = tmp_path / "fb"
    (fb / "lists").mkdir(parents=True)
    (fb / "lists" / "stale_verdicts.tsv").write_text(
        "vol01:182:9:11a\t20261113T1144\t作废\n", encoding="utf-8")
    bad_db = tmp_path / "db_is_a_dir"
    bad_db.mkdir()                      # sqlite3.connect 目录会抛异常
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(fb))
    monkeypatch.setenv("GUJI_GLYPH_DB", str(bad_db))
    assert stale_human_marks("vol01") == {"vol01:182:9:11a": "20261113T1144"}


def _stale_env(tmp_path, monkeypatch, tsv: str, evictions: list[tuple[str, str, str]]):
    import sqlite3
    fb = tmp_path / "fb"
    (fb / "lists").mkdir(parents=True)
    (fb / "lists" / "stale_verdicts.tsv").write_text(tsv, encoding="utf-8")
    db = tmp_path / "glyph.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE admissions (instance_id TEXT, char TEXT, provenance TEXT, evidence TEXT, admitted_at TEXT)")
    con.execute("CREATE TABLE evictions (instance_id TEXT, char TEXT, reason TEXT, at TEXT)")
    con.executemany("INSERT INTO evictions VALUES (?,?,NULL,?)", evictions)
    con.commit()
    con.close()
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(fb))
    monkeypatch.setenv("GUJI_GLYPH_DB", str(db))


def test_glyph_audit_mark_voids_only_the_evicted_char(tmp_path, monkeypatch):
    """库内审阅撤库留的标记只作废与被撤刻例原字相同的人裁（ZM 殿本 vol01 85:9:11：库里「曰」、现行人裁「淵」，11-18）。"""
    from open_guji_cv.feedback.lookup import stale_human_rules
    _stale_env(tmp_path, monkeypatch,
               "vol01:85:9:11\t20261118T0754\tglyph_audit evict evt_x_000011\n"
               "vol01:85:9:13\t20261118T0754\tglyph_audit evict evt_x_000012\n",
               [("v2:vol01:85:9:11", "曰", "2026-11-18T07:54:10+00:00"),
                ("v2:vol01:85:9:13", "曰", "2026-11-18T07:54:10+00:00")])
    assert stale_human_rules("vol01")["vol01:85:9:11"] == [("20261118T0754", {"evicted": {"曰"}})]
    log = EventLog(tmp_path / "ev")
    a = _ev("vol01:85:9:11", {"v": "confirm", "shape": "淵"}, 1); a.ts = "2026-11-10T01:22:14Z"
    b = _ev("vol01:85:9:13", {"v": "confirm", "shape": "曰"}, 2); b.ts = "2026-11-10T01:22:14Z"
    log.append([a, b])
    got = human_chars("vol01", log)
    assert got == {"vol01:85:9:11": "淵"}, "现行人裁不是被撤的字：照常生效；人裁就是被撤的字：作废"


def test_glyph_audit_mark_without_eviction_record_voids_all(tmp_path, monkeypatch):
    """取不到被撤刻例的原字（没有撤例审计）、或不是库内审阅来的标记：照旧全部作废。"""
    _stale_env(tmp_path, monkeypatch,
               "vol01:4:1:3\t20261118T0754\tglyph_audit relabel evt_y_000001\n"
               "vol01:4:1:4\t20261118T0754\t用户 作废\n",
               [("v2:vol01:4:1:4", "目", "2026-11-18T07:54:10+00:00"),
                ("v2:vol01:4:1:3", "目", "2026-11-18T08:30:00+00:00")])   # 撤例晚于标记：不算
    log = EventLog(tmp_path / "ev")
    a = _ev("vol01:4:1:3", {"v": "confirm", "shape": "文"}, 1); a.ts = "2026-11-10T00:00:00Z"
    b = _ev("vol01:4:1:4", {"v": "confirm", "shape": "文"}, 2); b.ts = "2026-11-10T00:00:00Z"
    log.append([a, b])
    assert human_chars("vol01", log) == {}


def test_glyph_audit_relabel_mark_keeps_verdicts_for_the_new_char(tmp_path, monkeypatch):
    """改标留的标记：人裁就是改标的新字的照常生效，说成别的字的作废（ZM vol01 8:9:12 库「曰」改「日」，现行人裁「日」）。"""
    _stale_env(tmp_path, monkeypatch,
               "vol01:8:9:12\t20261118T0754\tglyph_audit relabel evt_fix_000002\n"
               "vol01:8:9:13\t20261118T0754\tglyph_audit relabel evt_fix_000003\n",
               [("v2:vol01:8:9:12", "曰", "2026-11-18T07:54:10+00:00")])
    log = EventLog(tmp_path / "ev")
    rel = []
    for n, (k, ch) in enumerate((("vol01:8:9:12", "日"), ("vol01:8:9:13", "己")), start=2):
        e = make_event("fix", n, "glyph_audit", EventTarget(step="glyph_audit", unit="cell", key="v2:" + k),
                       {"v": "relabel", "char": ch, "instance_id": "v2:" + k}, source_format="server")
        e.id = f"evt_fix_{n:06d}"
        rel.append(e)
    a = _ev("vol01:8:9:12", {"v": "confirm", "shape": "日"}, 1); a.ts = "2026-11-15T03:15:19Z"
    b = _ev("vol01:8:9:13", {"v": "confirm", "shape": "已"}, 2); b.ts = "2026-11-15T03:15:19Z"
    log.append([a, b, *rel])
    assert human_chars("vol01", log) == {"vol01:8:9:12": "日"}
