# -*- coding: utf-8 -*-
"""`scripts/glyph_store_sync.py::acquire_feedback_lock`：按书各拿一把人裁写锁。

CV 总管 reply（`20260927-0050`）：这里此前是 `nullcontext()` 占位，H 的锁合入后
要换成真锁，且按书分别拿、不是整仓一把。这里补一份此前没有的单测。
"""

from __future__ import annotations

import importlib.util
import multiprocessing as mp
from pathlib import Path

import pytest


def _load():
    spec = importlib.util.spec_from_file_location(
        "glyph_store_sync", Path(__file__).resolve().parent.parent / "scripts" / "glyph_store_sync.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_only_books_with_feedback_dir_get_locked(tmp_path):
    m = _load()
    b1 = tmp_path / "book1"
    (b1 / "feedback").mkdir(parents=True)
    b2 = tmp_path / "book2"
    b2.mkdir()   # 没有 feedback/，不该被拿锁（也不该报错）

    with m.acquire_feedback_lock([b1, b2]):
        assert (b1 / "feedback" / ".write.lock").exists()
        assert not (b2 / "feedback").exists()


def _hold_lock_then_signal(feedback_dir: Path, ready_flag: Path, release_flag: Path) -> None:
    from open_guji_cv.feedback.lock import book_feedback_lock
    with book_feedback_lock(feedback_dir):
        ready_flag.write_text("1", encoding="utf-8")
        while not release_flag.exists():
            pass


def test_acquire_feedback_lock_blocks_concurrent_writer(tmp_path):
    """另一进程正持有这本书的锁时，`acquire_feedback_lock` 该等，不是绕过去。"""
    m = _load()
    b1 = tmp_path / "book1"
    (b1 / "feedback").mkdir(parents=True)
    ready, release = tmp_path / "ready", tmp_path / "release"

    ctx = mp.get_context("fork")
    p = ctx.Process(target=_hold_lock_then_signal, args=(b1 / "feedback", ready, release))
    p.start()
    try:
        for _ in range(200):
            if ready.exists():
                break
            import time
            time.sleep(0.01)
        assert ready.exists(), "子进程没能在超时内拿到锁"

        acquired = mp.Value("b", 0)

        def _try_acquire():
            with m.acquire_feedback_lock([b1]):
                acquired.value = 1

        import threading
        t = threading.Thread(target=_try_acquire)
        t.start()
        t.join(timeout=0.3)
        assert acquired.value == 0, "子进程还持锁时，主进程不该拿到同一把锁"
        release.write_text("1", encoding="utf-8")
        t.join(timeout=5)
        assert acquired.value == 1
    finally:
        release.write_text("1", encoding="utf-8")
        p.join(timeout=5)
        if p.is_alive():
            p.terminate()


def test_feedback_of_book_without_own_glyph_db_is_committed(tmp_path, monkeypatch):
    """借别家库的书（全唐文借四庫库）没有 output/glyph.db：它的 feedback/events 与
    consumed 也要进提交（2026-09-27，K 快照自动导入 §5；此前按有没有库挑书，整本漏掉）。"""
    import subprocess
    import sys
    m = _load()
    root = tmp_path / "ws"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "config", k, v], cwd=root, check=True)
    book = root / "qtw-draft"
    (book / "feedback" / "events").mkdir(parents=True)
    (book / "feedback" / "consumed").mkdir(parents=True)
    (book / "feedback" / "events" / "e.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    (book / "feedback" / "consumed" / "c.jsonl").write_text('{"b":1}\n', encoding="utf-8")
    monkeypatch.setattr(m, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(sys, "argv", ["glyph_store_sync.py", "--root", str(root), "--no-push"])
    assert m.main() == 0
    files = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.split()
    assert "qtw-draft/feedback/events/e.jsonl" in files
    assert "qtw-draft/feedback/consumed/c.jsonl" in files
