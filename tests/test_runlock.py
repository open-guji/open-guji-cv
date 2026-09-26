# -*- coding: utf-8 -*-
"""书级跑批锁与产物快照（core/runlock.py）。数据全在 tmp_path 里自造。"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import pytest

from open_guji_cv.core.runlock import (RunLockHeld, book_run_lock, lock_path, make_snapshot,
                                       read_holder)


def _hold_in_child(products, book, ready_file):
    """起一个子进程拿住锁，写出 ready 标志后睡着不放。"""
    code = textwrap.dedent(f"""
        import time, pathlib
        from open_guji_cv.core.runlock import book_run_lock
        with book_run_lock({book!r}, products=pathlib.Path({str(products)!r})):
            pathlib.Path({str(ready_file)!r}).write_text("1")
            time.sleep(30)
    """)
    return subprocess.Popen([sys.executable, "-c", code])


def _wait_ready(ready_file, proc):
    import time
    for _ in range(200):
        if ready_file.exists():
            return
        assert proc.poll() is None, "持锁子进程提前退出了"
        time.sleep(0.05)
    raise AssertionError("持锁子进程没就绪")


def test_second_holder_is_refused_and_sees_holder(tmp_path, monkeypatch):
    monkeypatch.delenv("GUJI_NO_RUN_LOCK", raising=False)
    ready = tmp_path / "ready"
    proc = _hold_in_child(tmp_path, "tbook", ready)
    try:
        _wait_ready(ready, proc)
        with pytest.raises(RunLockHeld) as ei:
            with book_run_lock("tbook", products=tmp_path):
                pass
        assert ei.value.holder.get("pid") == proc.pid
        assert "GUJI_PRODUCTS_DIR" in str(ei.value)
    finally:
        proc.kill()
        proc.wait()
    # 持有者一死锁就放，不留死锁
    with book_run_lock("tbook", products=tmp_path) as h:
        assert h["pid"] > 0
        assert read_holder(lock_path("tbook", tmp_path))["pid"] == h["pid"]
    assert read_holder(lock_path("tbook", tmp_path)) is None


def test_lock_is_per_book_and_per_products_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("GUJI_NO_RUN_LOCK", raising=False)
    ready = tmp_path / "ready"
    official = tmp_path / "official"
    proc = _hold_in_child(official, "tbook", ready)
    try:
        _wait_ready(ready, proc)
        with book_run_lock("other", products=official):
            pass
        with book_run_lock("tbook", products=tmp_path / "sandbox"):
            pass
    finally:
        proc.kill()
        proc.wait()


def test_env_disables_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_NO_RUN_LOCK", "1")
    with book_run_lock("tbook", products=tmp_path) as h:
        assert h is None
    assert not lock_path("tbook", tmp_path).exists()


def test_snapshot_copies_steps_and_is_readable_as_products_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("GUJI_NO_RUN_LOCK", raising=False)
    src = tmp_path / "products"
    for step in ("border_detect", "row_segment"):
        d = src / "tbook" / step
        d.mkdir(parents=True)
        (d / "p0001.json").write_text('{"x": 1}', encoding="utf-8")
    out = make_snapshot("tbook", ["row_segment"], "s1", products=src,
                        dest_root=tmp_path / "snap", code_rev="abc123")
    assert (out / "tbook" / "row_segment" / "p0001.json").read_text(encoding="utf-8") == '{"x": 1}'
    assert not (out / "tbook" / "border_detect").exists()
    meta = json.loads((out / "SNAPSHOT.json").read_text(encoding="utf-8"))
    assert meta["code_rev"] == "abc123" and meta["files"] == {"row_segment": 1}
    # 上游再改，快照不变
    (src / "tbook" / "row_segment" / "p0001.json").write_text('{"x": 2}', encoding="utf-8")
    assert (out / "tbook" / "row_segment" / "p0001.json").read_text(encoding="utf-8") == '{"x": 1}'
    with pytest.raises(FileExistsError):
        make_snapshot("tbook", ["row_segment"], "s1", products=src, dest_root=tmp_path / "snap")
    with pytest.raises(FileNotFoundError):
        make_snapshot("tbook", ["nope"], "s2", products=src, dest_root=tmp_path / "snap")
