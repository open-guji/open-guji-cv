# -*- coding: utf-8 -*-
"""字形字段合法性校验（`feedback/mojibake.py`）＋ 写入口拒写／读取处跳过（2026-09-27）。

背景：`vol01-p1-30-confirm-20260916` 一批事件的 `shape`/`reading` 在写盘前
已被 UTF-8→cp1252 误双重编码（「内」存成「å†…」），原样流进
`feedback.lookup.human_chars()` 后把「一个字位=一个字符」的假设打破，
`report/collate.py::diff_page` 逐位比对下标错位崩溃（P cross 1717）。

三层各测一遍：
1. `mojibake.py` 本身的判据（合法/可还原/需人判）；
2. 写入口 `EventLog.append()` 对不合格字段直接拒；
3. 读取处 `lookup.human_chars()` / `steps.seed_admit._human_shapes()` 跳过
   不合格记录、只记 warning，不让它混进产出。
"""
from __future__ import annotations

import sqlite3

import pytest

from open_guji_cv.errors import BadRequest
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
from open_guji_cv.feedback.lookup import human_chars
from open_guji_cv.feedback.mojibake import (classify_shape_field, is_legal_shape,
                                            is_ids_string, is_variation_sequence, unmojibake)

MOJIBAKE_NEI = "å†…"       # 「内」被 cp1252 误解码
MOJIBAKE_CHOU = "é·¹"      # 「鷹」被 cp1252 误解码


def _ev(key: str, payload: dict, seq: int, batch: str = "b", ts: str | None = None):
    _, pg, col, slot = key.split(":")
    e = make_event(batch, seq, "confirm",
                   EventTarget(step="seed_admit", unit="cell", key=key, book="vol01",
                               page=int(pg), col=int(col), slot=int(slot)),
                   payload, source_format="server")
    if ts:
        e.ts = ts
    return e


# ── 1. mojibake.py 判据本身 ─────────────────────────────────────────────

def test_single_char_always_legal():
    assert is_legal_shape("内")
    assert is_legal_shape("甲")


def test_none_and_empty_are_legal():
    assert is_legal_shape(None)
    assert is_legal_shape("")


def test_mojibake_is_illegal_and_recoverable():
    assert not is_legal_shape(MOJIBAKE_NEI)
    assert classify_shape_field(MOJIBAKE_NEI) == "recoverable"
    assert unmojibake(MOJIBAKE_NEI) == "内"


def test_garbage_is_needs_human():
    assert classify_shape_field("abc") == "needs_human"
    assert unmojibake("abc") == "abc"          # 还原不了，原样返回


def test_ids_string_is_legal_multi_codepoint():
    assert is_ids_string("⿰亻斯")
    assert is_legal_shape("⿰亻斯")
    assert classify_shape_field("⿰亻斯") == "legal"


def test_pua_with_selector_is_legal():
    pua = chr(0xE000) + chr(0xFE00)
    assert is_variation_sequence(pua)
    assert is_legal_shape(pua)


def test_encoded_cjk_with_variation_selector_is_legal():
    """基字不限 PUA——已编码的普通汉字 + 变体选择符也是合法的单字位（IVS）。
    这是 `console/routers/step8.py`"都不对，填 X+VS17"的真实场景，第一版
    只认 PUA 基字，把「葛」+ VS17 误判成不合法，`test_step8_routes.py::
    test_decide_accepts_variation_selector_fix` 实测踩过。"""
    ge_vs17 = "葛" + "\U000E0100"
    assert is_variation_sequence(ge_vs17)
    assert is_legal_shape(ge_vs17)
    assert classify_shape_field(ge_vs17) == "legal"


def test_already_cjk_multi_char_not_treated_as_mojibake():
    """全串已是 CJK 类字符（不含 IDC）——两个正常汉字连在一起既不合法也不可还原，
    该归需人判，不该被 `unmojibake` 误改写（`unmojibake` 对这种输入原样返回）。"""
    s = "内外"
    assert not is_legal_shape(s)
    assert unmojibake(s) == s
    assert classify_shape_field(s) == "needs_human"


# ── 2. 写入口拒写 ────────────────────────────────────────────────────────

def test_append_rejects_mojibake_shape(tmp_path):
    log = EventLog(tmp_path)
    with pytest.raises(BadRequest, match="不合法"):
        log.append([_ev("vol01:4:1:3", {"v": "confirm", "shape": MOJIBAKE_NEI}, 1)])


def test_append_rejects_mojibake_reading(tmp_path):
    log = EventLog(tmp_path)
    with pytest.raises(BadRequest, match="不合法"):
        log.append([_ev("vol01:4:1:3", {"v": "confirm", "shape": "内", "reading": MOJIBAKE_NEI}, 1)])


def test_append_allows_legal_single_char(tmp_path):
    log = EventLog(tmp_path)
    n = log.append([_ev("vol01:4:1:3", {"v": "confirm", "shape": "内"}, 1)])
    assert n == 1


def test_append_allows_ids_string_shape(tmp_path):
    """`char` 字段允许合法多码位（IDS 串）——`glyph_audit` 一类未收字登记事件用得到。"""
    log = EventLog(tmp_path)
    n = log.append([_ev("vol01:4:1:3", {"v": "confirm", "char": "⿰亻斯"}, 1)])
    assert n == 1


def test_append_rejects_one_bad_event_blocks_whole_batch(tmp_path):
    """整批一起拒——不是「好的先写、坏的跳过」，否则坏数据可能已经半写进去。"""
    log = EventLog(tmp_path)
    with pytest.raises(BadRequest):
        log.append([_ev("vol01:4:1:3", {"v": "confirm", "shape": "内"}, 1),
                    _ev("vol01:4:1:4", {"v": "confirm", "shape": MOJIBAKE_CHOU}, 2)])
    assert log.read("b") == []          # 一条都没落盘


# ── 3. 读取处跳过 + warning，且更正事件能压过旧的乱码（后到覆盖）─────────

def test_human_chars_skips_mojibake_with_warning(tmp_path, caplog):
    """乱码事件写进日志文件本身仍可能发生（老数据、或绕过写入口的历史批次）——
    这里直接造一个已经落盘的坏文件模拟老数据，不经 `append`（写入口的闸门
    只挡新写入，不负责清洗已经在磁盘上的东西）。"""
    import json
    log = EventLog(tmp_path)
    path = log.batch_path("legacy")
    path.parent.mkdir(parents=True, exist_ok=True)
    bad = _ev("vol01:4:1:3", {"v": "confirm", "shape": MOJIBAKE_NEI}, 1, batch="legacy")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(bad.model_dump(mode="json"), ensure_ascii=False) + "\n")
    with caplog.at_level("WARNING"):
        got = human_chars("vol01", log)
    assert got == {}
    assert any("不合法" in r.message for r in caplog.records)


def test_human_chars_correction_event_wins_over_mojibake(tmp_path):
    """追加同格更正事件（后到覆盖）：乱码那条虽然仍在日志里，但更晚的合法事件
    才是"生效"的那条——这正是 H 任务书的修复方式（不改写旧行，追加更正）。"""
    import json
    log = EventLog(tmp_path)
    path = log.batch_path("legacy")
    path.parent.mkdir(parents=True, exist_ok=True)
    bad = _ev("vol01:4:1:3", {"v": "confirm", "shape": MOJIBAKE_NEI}, 1, batch="legacy",
              ts="2026-09-16T23:23:49Z")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(bad.model_dump(mode="json"), ensure_ascii=False) + "\n")
    fix = _ev("vol01:4:1:3", {"v": "confirm", "shape": "内", "reason": "mojibake_fix_20260916"},
              1, batch="H-mojibake-fix-20260927", ts="2026-09-27T00:00:00Z")
    log.append([fix])
    assert human_chars("vol01", log) == {"vol01:4:1:3": "内"}


# ── `_human_shapes`（字形库读取处）───────────────────────────────────────

def test_human_shapes_skips_illegal_db_char(tmp_path, caplog):
    """库里的老坏数据（写入口加校验之前进库的）：跳过并记 warning，不让它混进
    `AdmitRec.char`。这里直接摆一张最小 schema 的库，不依赖真 `GlyphDB`。"""
    from open_guji_cv.steps.seed_admit import _human_shapes
    db_path = tmp_path / "glyph.db"
    con = sqlite3.connect(str(db_path))
    con.executescript("""
        CREATE TABLE glyphs (glyph_id INTEGER PRIMARY KEY, char TEXT);
        CREATE TABLE exemplars (instance_id TEXT, glyph_id INTEGER);
        CREATE TABLE admissions (instance_id TEXT, provenance TEXT, char TEXT);
    """)
    con.execute("INSERT INTO glyphs VALUES (1, ?)", (MOJIBAKE_NEI,))
    con.execute("INSERT INTO exemplars VALUES ('v2:vol01:4:1:3', 1)")
    con.execute("INSERT INTO admissions VALUES ('v2:vol01:4:1:3', 'human', ?)", (MOJIBAKE_NEI,))
    con.execute("INSERT INTO glyphs VALUES (2, '内')")
    con.execute("INSERT INTO exemplars VALUES ('v2:vol01:4:1:4', 2)")
    con.execute("INSERT INTO admissions VALUES ('v2:vol01:4:1:4', 'human', '内')")
    con.commit()
    con.close()
    _human_shapes.cache_clear()
    with caplog.at_level("WARNING"):
        got = _human_shapes(str(db_path))
    _human_shapes.cache_clear()
    assert got == {"vol01:4:1:4": "内"}
    assert any("不合法" in r.message for r in caplog.records)
