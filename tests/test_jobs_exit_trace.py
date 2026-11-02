# -*- coding: utf-8 -*-
"""执行方退出痕迹：上次存活／退出原因的报告、SIGTERM 写日志后退出、写不进去不影响。"""
from __future__ import annotations

import signal

import pytest

from open_guji_cv.jobs import exit_trace as XT


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    monkeypatch.setattr(XT, "atexit", type("A", (), {"register": staticmethod(lambda *a, **k: None)}))
    monkeypatch.setattr(XT, "_alive_thread", lambda path: None)
    yield
    for s, h in saved.items():
        signal.signal(s, h)
    XT._state.update(why=None, stop=None)


def test_last_record_parses_alive_and_exit(tmp_path):
    f = tmp_path / "alive"
    f.write_text("alive 1000 pid 5\nexit 2000 收到 SIGTERM\n", encoding="utf-8")
    assert XT.last_record(f) == ("exit", 2000.0, "收到 SIGTERM")
    assert XT.last_record(tmp_path / "none") is None


def test_start_reports_previous_exit_reason(tmp_path):
    (tmp_path / "alive").write_text("exit 1000 收到 SIGTERM\n", encoding="utf-8")
    said = []
    XT.start(tmp_path, said.append, now=1100.0)
    assert any("上次退出原因：收到 SIGTERM" in s for s in said)


def test_start_reports_gap_when_no_exit_record(tmp_path):
    (tmp_path / "alive").write_text("alive 1000 pid 5\n", encoding="utf-8")
    said = []
    XT.start(tmp_path, said.append, now=1000.0 + 3600)
    assert any("没有退出记录" in s and "整机暂停" in s for s in said)


def test_start_quiet_when_last_alive_is_recent(tmp_path):
    (tmp_path / "alive").write_text("alive 1000 pid 5\n", encoding="utf-8")
    said = []
    XT.start(tmp_path, said.append, now=1030.0)
    assert not any("没有退出记录" in s for s in said)


def test_sigterm_logs_then_exits_with_reason(tmp_path):
    said = []
    XT.start(tmp_path, said.append, now=1000.0)
    handler = signal.getsignal(signal.SIGTERM)
    with pytest.raises(SystemExit) as ei:
        handler(signal.SIGTERM, None)
    assert ei.value.code == 128 + signal.SIGTERM
    assert any("收到 SIGTERM" in s for s in said)
    XT.note_exit(tmp_path / "alive", XT._state["why"])
    assert (tmp_path / "alive").read_text(encoding="utf-8").splitlines()[-1].endswith("收到 SIGTERM")


def test_note_exit_writes_once(tmp_path):
    XT.start(tmp_path, lambda s: None, now=1000.0)
    XT.note_exit(tmp_path / "alive", "正常返回")
    XT.note_exit(tmp_path / "alive", "又来一次")
    lines = (tmp_path / "alive").read_text(encoding="utf-8").splitlines()
    assert [ln for ln in lines if ln.startswith("exit")] == [lines[-1]] and lines[-1].endswith("正常返回")


def test_unwritable_home_does_not_raise(tmp_path):
    XT.start(tmp_path / "missing" / "dir", lambda s: None, now=1000.0)   # 目录不存在：写不进去，但不抛
    XT.note_exit(tmp_path / "missing" / "dir" / "alive", "正常返回")
