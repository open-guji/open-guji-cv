# -*- coding: utf-8 -*-
"""任务的工作区是工单的一部分，不受「当前工作区」怎么变的影响。

背景（2026-09-15）：控制台支持每个标签页各自一个工作区之后，「当前工作区」
成了会变的东西。跑批子进程原先直接 `os.environ.copy()`，于是**排队中**的任务
会拿到「轮到它开跑那一刻」的值——切一次工作区，后面排队的任务就把产物写到
别的工作区去了，不报错，只是安静地写错地方。

用户定的边界：工作区是浏览器/请求的状态，**不能给 job 用**。job 的工作区在
入队时写进 `JobSpec.workspace`，出队拼环境只认这一份。
"""
from __future__ import annotations

import os
import sys
import time

import pytest

from open_guji_cv.console.jobs import TERMINAL, JobRunner, JobSpec

PROBE = ["-c", "import os;print('SEES=' + os.environ.get('GUJI_WORKSPACE','<unset>'))"]


def _run_and_read(runner: JobRunner, jobs) -> list[str]:
    for _ in range(240):
        if all(j.status in TERMINAL for j in jobs):
            break
        time.sleep(0.25)
    out = []
    for j in jobs:
        log = (runner.root / f"{j.id}.log").read_text(encoding="utf-8", errors="replace")
        out.append(next((l.split("=", 1)[1].strip() for l in log.splitlines()
                         if l.startswith("SEES=")), "<no-output>"))
    return out


def test_submit_requires_explicit_workspace(tmp_path):
    """不给工作区就拒收——不能悄悄兜底成「当前那个」，那正是要避免的耦合。"""
    r = JobRunner(tmp_path)
    with pytest.raises(ValueError, match="workspace"):
        r.submit(JobSpec(book="b", pipeline="p"))


def test_queued_jobs_keep_their_own_workspace(tmp_path, monkeypatch):
    """三张工单各写各的工作区；排队期间把进程的 GUJI_WORKSPACE 改掉，
    每个子进程看到的仍必须是**自己工单上**那个。"""
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path / "at_submit"))
    r = JobRunner(tmp_path / "runs")

    want = [str(tmp_path / "ws_a"), str(tmp_path / "ws_b"), ""]
    jobs = []
    for ws in want:
        j = r.submit(JobSpec(book="b", pipeline="p", workspace=ws))
        j.argv = [sys.executable, *PROBE]     # 只打印环境，不真跑管线
        jobs.append(j)

    # 排队/开跑期间「切工作区」
    os.environ["GUJI_WORKSPACE"] = str(tmp_path / "switched_later")

    seen = _run_and_read(r, jobs)
    assert seen == [want[0], want[1], "<unset>"], (
        f"工单的工作区被全局值带跑偏了：期望 {want}，实际 {seen}")
