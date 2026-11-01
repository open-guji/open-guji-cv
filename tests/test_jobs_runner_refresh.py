# -*- coding: utf-8 -*-
"""dev 有更新：空闲时拉新代码、原参数自己 exec；手上有单就等单跑完；拉不动就照旧退出。"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from open_guji_cv.jobs import runner as R
from open_guji_cv.jobs import store as S


class ExecCalled(BaseException):
    """替身 os.execv：记下调用就抛出去结束循环（BaseException，不会被循环里的 except Exception 吞掉）。"""


def _setup(monkeypatch, tmp_path, *, claims, outdated_seq, refresh_ok):
    monkeypatch.setattr(R, "HOME", tmp_path)
    monkeypatch.setattr(S, "who", lambda: "worker-test")
    monkeypatch.setattr(R, "_runner_commit", lambda: None)
    monkeypatch.setattr(R, "_preflight", lambda: None)
    monkeypatch.setattr(R, "_disk_gate", lambda say=print: None)
    monkeypatch.setattr(R, "_last_book", lambda: None)
    monkeypatch.setattr(R, "_remember_book", lambda book: None)
    monkeypatch.setattr(R.SP, "summary", lambda spec: "")
    monkeypatch.setattr(R.BOARD, "publish", lambda *a, **kw: None)
    monkeypatch.setattr(R.time, "sleep", lambda s: None)

    order: list[str] = []
    outdated = iter(outdated_seq)
    monkeypatch.setattr(R, "_runner_outdated", lambda: (order.append("outdated"), next(outdated))[1])
    monkeypatch.setattr(R, "_refresh_runner", lambda: (order.append("refresh"), refresh_ok)[1])

    execs: list[tuple] = []

    def fake_execv(path, argv):
        execs.append((path, list(argv)))
        raise ExecCalled()

    monkeypatch.setattr(R.os, "execv", fake_execv)

    queue = list(claims)

    def fake_db(fn, *a, **kw):
        if fn is S.reap:
            return []
        if fn is S.claim:
            return queue.pop(0) if queue else None
        return None

    class FakeJob:
        def __init__(self, job, att, db, dry=False):
            self.job = job

        def run(self):
            order.append(f"run#{self.job['id']}")
            return "succeeded"

    monkeypatch.setattr(R, "Job", FakeJob)
    return fake_db, order, execs


def test_idle_outdated_refreshes_then_execs_with_original_argv(monkeypatch, tmp_path):
    fake_db, order, execs = _setup(monkeypatch, tmp_path, claims=[None], outdated_seq=[True], refresh_ok=True)
    with pytest.raises(ExecCalled):
        _run(fake_db, idle_minutes=86400)
    assert order == ["outdated", "refresh"]
    assert execs == [(sys.executable, list(sys.orig_argv))]


def test_idle_outdated_but_refresh_fails_exits_without_exec(monkeypatch, tmp_path):
    fake_db, order, execs = _setup(monkeypatch, tmp_path, claims=[None], outdated_seq=[True], refresh_ok=False)
    said: list[str] = []
    done = _run(fake_db, idle_minutes=86400, say=said.append)
    assert done == 0
    assert execs == []
    assert any("拉不动" in s for s in said)


def test_job_in_progress_finishes_before_the_check(monkeypatch, tmp_path):
    job = {"id": 7, "kind": "rerun", "book": "vol01", "spec": {}}
    fake_db, order, execs = _setup(monkeypatch, tmp_path, claims=[(job, {"n": 1}), None],
                                   outdated_seq=[False, True], refresh_ok=True)
    with pytest.raises(ExecCalled):
        _run(fake_db, idle_minutes=86400)
    # 单在检查之前就跑完了；检查是在两张单之间做的，换代码只发生在手上没单的时候
    assert order == ["outdated", "run#7", "outdated", "refresh"]


def _run(fake_db, *, idle_minutes, say=lambda *a: None):
    orig = R.S.DB
    try:
        R.S.DB = lambda: fake_db
        return R.work(idle_minutes=idle_minutes, say=say)
    finally:
        R.S.DB = orig


def _git(cwd, *args, env=None):
    base = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True,
                          env={**base, **(env or {})}).stdout.strip()


def test_refresh_fast_forwards_checkout_to_origin_dev(monkeypatch, tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "dev")
    (origin / "a.txt").write_text("1")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "one")
    runner = tmp_path / "runner"
    _git(tmp_path, "clone", "-q", str(origin), str(runner))

    (origin / "a.txt").write_text("2")
    _git(origin, "commit", "-q", "-am", "two")
    new_tip = _git(origin, "rev-parse", "HEAD")

    monkeypatch.setattr(R, "RUNNER_ROOT", runner)
    _git(runner, "fetch", "-q", "origin", "dev")
    assert R._refresh_runner() is True
    assert _git(runner, "rev-parse", "HEAD") == new_tip


def test_refresh_refuses_when_checkout_has_diverged(monkeypatch, tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "dev")
    (origin / "a.txt").write_text("1")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "one")
    runner = tmp_path / "runner"
    _git(tmp_path, "clone", "-q", str(origin), str(runner))

    (origin / "a.txt").write_text("2")
    _git(origin, "commit", "-q", "-am", "two")
    (runner / "local.txt").write_text("local")
    _git(runner, "add", ".")
    _git(runner, "commit", "-q", "-m", "local only")

    monkeypatch.setattr(R, "RUNNER_ROOT", runner)
    _git(runner, "fetch", "-q", "origin", "dev")
    assert R._refresh_runner() is False
