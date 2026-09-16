# -*- coding: utf-8 -*-
"""任务日志的 tail 与 SSE 编码——**两件事，分开写**。

`app.py` 原先把它们揉在 `_tail_log` 一个生成器里（25 行）：一边 tail 文件、
一边拼 `data: {...}\\n\\n`。tail 那部分是通用的（`guji runs log -f` 要用同一套），
SSE 编码那三行才是控制台专有。分开之后 CLI 直接消费 `tail_job()` 的字典流。

行为与原来逐字一致：0.4s 轮询、15s 一次 keepalive、任务进终态发一帧 `complete`
再收；任务不存在发一帧 `error` 就收。
"""
from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

from .jobs import TERMINAL, JobRunner

POLL_S = 0.4
KEEPALIVE_S = 15


def tail_job(runner: JobRunner, job_id: str) -> Iterator[dict[str, Any] | None]:
    """跟一个任务的日志。产出 `{"type": "line"|"complete"|"error", ...}`；
    `None` 表示「这一轮没有新内容」，由调用方决定要不要发心跳。"""
    job = runner.get(job_id)
    if not job:
        yield {"type": "error", "line": "没有这个任务"}
        return
    path = runner.log_path(job_id)
    pos = 0
    while True:
        if path.exists():
            with open(path, "rb") as f:
                f.seek(pos)
                chunk = f.read()
                pos = f.tell()
            for line in chunk.decode("utf-8", errors="replace").splitlines():
                if line.strip():
                    yield {"type": "line", "line": line}
        job = runner.get(job_id)
        if job and job.status in TERMINAL:
            yield {"type": "complete", **job.to_dict()}
            return
        yield None
        time.sleep(POLL_S)


def sse(runner: JobRunner, job_id: str) -> Iterator[bytes]:
    """把 `tail_job` 的字典流编成 SSE 帧；空闲超过 15 秒发一条 keepalive 注释。"""
    last_beat = time.time()
    for ev in tail_job(runner, job_id):
        if ev is None:
            if time.time() - last_beat > KEEPALIVE_S:
                yield b": keepalive\n\n"
                last_beat = time.time()
            continue
        yield b"data: " + json.dumps(ev, ensure_ascii=False).encode() + b"\n\n"
