# -*- coding: utf-8 -*-
"""D 脚本（撤 v1 conflict_human 里的读错例，`scripts/evict_v1_conflict_human_reading_errors.py`）：
预览不写盘、`--apply` 才写事件+撤库、目标格现算（不写死 id）、`--book` 排除同字异码位对。"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from open_guji_cv.clustering.glyph_db import GlyphDB

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "evict_v1_conflict_human_reading_errors",
    REPO / "scripts" / "evict_v1_conflict_human_reading_errors.py")
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)


def _png(k: int) -> bytes:
    img = np.full((64, 64), 255, np.uint8)
    cv2.rectangle(img, (8 + k, 8), (54, 54 - k), 0, 3)
    return cv2.imencode(".png", img)[1].tobytes()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """一个真冲突：v1 `vol01:3:4:11` 记「己」，人裁 `v2:vol01:3:4:12` 同一块图记「庚」——
    两字不相干，不是码位变体，是 v1 当年读错了。"""
    db_path = tmp_path / "g.db"
    g = GlyphDB(db_path)
    g.admit_instance("vol01:3:4:11", "己", _png(0), provenance="align")
    g.admit_instance("v2:vol01:3:4:12", "庚", _png(0), provenance="human")
    g.conn.execute("UPDATE sources SET pipeline_version='v1' WHERE source_id='vol01'")
    g.conn.commit()
    g.close()
    m = tmp_path / "map.jsonl"
    m.write_text(json.dumps({"v1": "vol01:3:4:11", "cell": "vol01:3:4:12", "status": "exact",
                             "cov": 0.999, "label": "?"}) + "\n", encoding="utf-8")
    feedback = tmp_path / "feedback"
    monkeypatch.setenv("GUJI_GLYPH_DB", str(db_path))
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(feedback))
    return db_path, m, feedback


def _run(monkeypatch, m, *extra):
    monkeypatch.setattr(sys, "argv", ["x", str(m), *extra])
    assert D.main() == 0


def _event_files(feedback: Path) -> list[Path]:
    d = feedback / "events"
    return sorted(d.glob("*.jsonl")) if d.exists() else []


def test_preview_finds_target_but_writes_nothing(env, monkeypatch, capsys):
    db_path, m, feedback = env
    _run(monkeypatch, m)
    out = capsys.readouterr().out
    assert "现算 conflict_human：1 条" in out
    assert "vol01:3:4:11" in out and "'己'" in out and "'庚'" in out
    assert _event_files(feedback) == []                    # 预览不写事件
    c = sqlite3.connect(db_path)
    assert c.execute("SELECT 1 FROM instances WHERE instance_id=?",
                     ("vol01:3:4:11",)).fetchone() is not None    # glyph.db 没被撤
    c.close()


def test_apply_writes_one_event_and_evicts_v1_only(env, monkeypatch, capsys):
    db_path, m, feedback = env
    _run(monkeypatch, m, "--apply")
    files = _event_files(feedback)
    assert len(files) == 1
    rec = json.loads(files[0].read_text(encoding="utf-8").splitlines()[0])
    assert rec["kind"] == "glyph_audit"
    assert rec["payload"]["v"] == "evict" and rec["payload"]["target"] == "vol01:3:4:11"
    c = sqlite3.connect(db_path)
    assert c.execute("SELECT 1 FROM instances WHERE instance_id=?",
                     ("vol01:3:4:11",)).fetchone() is None         # v1 撤了
    assert c.execute("SELECT 1 FROM instances WHERE instance_id=?",
                     ("v2:vol01:3:4:12",)).fetchone() is not None  # 人裁没动
    c.close()
    # 撤完之后再跑一遍预览：这条已经不在库里了，现算目标里也没有它
    capsys.readouterr()
    _run(monkeypatch, m)
    out = capsys.readouterr().out
    assert "现算 conflict_human：0 条" in out
    assert _event_files(feedback) == files                        # 第二遍没有再写新事件


def test_no_targets_writes_nothing(env, monkeypatch, capsys):
    """`--apply` 但现算出来 0 条目标：不该写空事件文件。"""
    db_path, m, feedback = env
    c = sqlite3.connect(db_path)
    c.execute("DELETE FROM instances WHERE instance_id=?", ("vol01:3:4:11",))
    c.commit()
    c.close()
    _run(monkeypatch, m, "--apply")
    assert _event_files(feedback) == []


def test_book_codepoint_equal_pair_is_excluded(env, monkeypatch, capsys):
    """己/庚 按书 `codepoints` 配置算同一个字时，不是「读错」，是同字异码位——
    这类交给 `glyph_v1_rekey.py --book` 重键落地，本脚本不该碰它。"""
    db_path, m, feedback = env
    import open_guji_cv.core.book as book_mod
    fake_book = book_mod.BookSpec(id="vol01", title="t", raw_dir=Path("."), codepoints={"己": "庚"})
    monkeypatch.setattr(book_mod, "load_book", lambda book_id: fake_book)
    _run(monkeypatch, m, "--book", "vol01")
    out = capsys.readouterr().out
    assert "现算 conflict_human：0 条" in out
    assert _event_files(feedback) == []
    c = sqlite3.connect(db_path)
    assert c.execute("SELECT 1 FROM instances WHERE instance_id=?",
                     ("vol01:3:4:11",)).fetchone() is not None    # 没被误撤
    c.close()
