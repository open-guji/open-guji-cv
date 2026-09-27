# -*- coding: utf-8 -*-
"""`scripts/glyph_codepoint_unify.py`：书级码位统一——库/释读/人裁裁决三处
一起改成本书 `codepoints` 指定的码位；dry-run 不落地；apply 幂等。"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

BOOK = "keben"


def _tiny_patch(size: int = 64) -> bytes:
    img = np.full((size, size), 255, np.uint8)
    cv2.rectangle(img, (size // 4, size // 4), (3 * size // 4, 3 * size // 4), 0, -1)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return bytes(buf)


def _seed_library(db_path):
    """造三条本书库实例：v1 机器准入 2 条（1 别 1 別）、v2 人裁 1 条（別）；
    外加一条别的书（不该被动）与一条字体来源（永远不该被动）。"""
    from open_guji_cv.clustering.glyph_db import GlyphDB

    db = GlyphDB(db_path)
    db.admit_instance(f"{BOOK}:1:1:1", "别", _tiny_patch(), provenance="align")
    db.admit_instance(f"{BOOK}:1:1:2", "別", _tiny_patch(), provenance="align")
    db.admit_instance(f"v2:{BOOK}:1:1:3", "別", _tiny_patch(), provenance="human")
    db.admit_instance("otherbook:1:1:1", "別", _tiny_patch(), provenance="align")
    db.admit_instance("font:iming:別", "別", _tiny_patch(), provenance="align",
                      edition_tag="font:iming")
    db.close()


def _seed_human_event(ws, key: str, shape: str):
    """造一条「历史」人裁事件——`ts` 钉在过去，不用墙钟时间：脚本的改判事件
    是**新写**的，同一测试秒内两条事件靠墙钟时间分不出先后，而
    `human_chars` 按 `(ts, batch, seq)` 排序取最后一条，ts 打平就要退回按
    批次名字符串比大小，跟真实场景（原裁决本来就是历史数据）不是一回事。"""
    from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
    from open_guji_cv.feedback.harvest import parse_card_id

    log = EventLog()
    ev = make_event("keben-decide", 1, "confirm",
                    EventTarget(step="context_decide", unit="cell", key=key,
                               **parse_card_id(key)),
                    {"v": "confirm", "shape": shape}, ts="2020-01-01T00:00:00Z")
    log.append([ev])


def test_dry_run_finds_matches_without_writing(ws, monkeypatch):
    from open_guji_cv.core.book import set_codepoints
    from open_guji_cv.core.workspace import glyph_db_path

    set_codepoints(BOOK, {"别": "別"})
    _seed_library(glyph_db_path())
    _seed_human_event(ws, f"{BOOK}:1:1:2", "別")   # 已是目标码位，不该出现在「别」的匹配里
    _seed_human_event(ws, f"{BOOK}:2:1:1", "别")   # 待改判

    import glyph_codepoint_unify as u
    from open_guji_cv.core.book import load_book

    book = load_book(BOOK)
    rep = u.scan(BOOK, book.codepoints, glyph_db_path())
    pair = rep["pairs"]["别→別"]
    assert pair["library"]["n"] == 1                 # 只有 keben:1:1:1，另两条不是「别」库项
    assert pair["library"]["sample"] == [f"{BOOK}:1:1:1"]
    assert pair["human_chars"]["n"] == 1
    assert f"{BOOK}:2:1:1" in pair["human_chars"]["sample"]

    # dry-run 没有 apply 就没有改库/写事件
    import sqlite3
    conn = sqlite3.connect(f"file:{glyph_db_path()}?mode=ro", uri=True)
    label = conn.execute("SELECT label FROM instances WHERE instance_id=?",
                         (f"{BOOK}:1:1:1",)).fetchone()[0]
    conn.close()
    assert label == "别"


def test_apply_relabels_library_admissions_and_events(ws):
    from open_guji_cv.core.book import load_book, set_codepoints
    from open_guji_cv.core.workspace import glyph_db_path

    set_codepoints(BOOK, {"别": "別"})
    _seed_library(glyph_db_path())
    _seed_human_event(ws, f"{BOOK}:2:1:1", "别")

    import glyph_codepoint_unify as u
    book = load_book(BOOK)
    rep = u.apply(BOOK, book.codepoints, glyph_db_path())
    assert rep["pairs"]["别→別"]["library"] == 1
    assert rep["pairs"]["别→別"]["admissions"] == 1
    assert rep["pairs"]["别→別"]["human_events"] == 1

    import sqlite3
    conn = sqlite3.connect(f"file:{glyph_db_path()}?mode=ro", uri=True)
    row = conn.execute("SELECT label, semantic, unicode_cp FROM instances WHERE instance_id=?",
                       (f"{BOOK}:1:1:1",)).fetchone()
    assert row == ("別", "別", ord("別"))
    adm_char = conn.execute("SELECT char FROM admissions WHERE instance_id=?",
                            (f"{BOOK}:1:1:1",)).fetchone()[0]
    assert adm_char == "別"
    # 别的书、字体来源不该被动
    assert conn.execute("SELECT label FROM instances WHERE instance_id='otherbook:1:1:1'"
                        ).fetchone()[0] == "別"           # 本来就是別，不受影响不代表没查
    assert conn.execute("SELECT label FROM instances WHERE instance_id='font:iming:別'"
                        ).fetchone()[0] == "別"
    conn.close()

    from open_guji_cv.feedback.lookup import human_chars
    assert human_chars(BOOK, bind=False).get(f"{BOOK}:2:1:1") == "別"


def test_apply_merges_glyph_heads(ws):
    """`别` 字头的 n_confirmed 并进 `別`，`别` 字头本身消失，exemplars 改指。"""
    from open_guji_cv.core.book import load_book, set_codepoints
    from open_guji_cv.core.workspace import glyph_db_path
    from open_guji_cv.clustering.glyph_db import GlyphDB

    set_codepoints(BOOK, {"别": "別"})
    db_path = glyph_db_path()
    db = GlyphDB(db_path)
    db.admit_instance(f"{BOOK}:1:1:1", "别", _tiny_patch(), provenance="align")
    db.admit_instance(f"{BOOK}:1:1:2", "別", _tiny_patch(), provenance="align")
    db.admit_instance(f"{BOOK}:1:1:3", "別", _tiny_patch(), provenance="align")
    edition = db.book_edition() or f"{BOOK}:1:1:1".split(":")[0]
    db.close()

    import glyph_codepoint_unify as u
    book = load_book(BOOK)
    u.apply(BOOK, book.codepoints, db_path)

    import sqlite3
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = conn.execute("SELECT char, n_confirmed FROM glyphs WHERE edition_tag=?",
                        (edition,)).fetchall()
    conn.close()
    chars = {c: n for c, n in rows}
    assert "别" not in chars
    assert chars.get("別") == 3           # 1（原 别）+ 2（原 別）


def test_apply_is_idempotent(ws):
    from open_guji_cv.core.book import load_book, set_codepoints
    from open_guji_cv.core.workspace import glyph_db_path

    set_codepoints(BOOK, {"别": "別"})
    _seed_library(glyph_db_path())
    _seed_human_event(ws, f"{BOOK}:2:1:1", "别")

    import glyph_codepoint_unify as u
    book = load_book(BOOK)
    first = u.apply(BOOK, book.codepoints, glyph_db_path())
    assert first["pairs"]["别→別"]["library"] == 1

    second = u.apply(BOOK, book.codepoints, glyph_db_path())
    assert second["pairs"]["别→別"] == {"library": 0, "admissions": 0, "human_events": 0}

    rep = u.scan(BOOK, book.codepoints, glyph_db_path())
    assert rep["pairs"]["别→別"]["library"]["n"] == 0
    assert rep["pairs"]["别→別"]["human_chars"]["n"] == 0


def test_no_codepoints_configured_is_a_noop(ws, capsys):
    from open_guji_cv.core.workspace import glyph_db_path

    _seed_library(glyph_db_path())
    import glyph_codepoint_unify as u
    from open_guji_cv.core.book import load_book

    book = load_book(BOOK)
    assert book.codepoints == {}
    # scan/apply 拿到空 mapping 时都该是空操作（main() 自己会在这一步直接返回，
    # 这里直接测底层函数：空字典迭代 0 次）
    assert u.scan(BOOK, {}, glyph_db_path())["pairs"] == {}
    assert u.apply(BOOK, {}, glyph_db_path())["pairs"] == {}
