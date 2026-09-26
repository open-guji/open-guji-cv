# -*- coding: utf-8 -*-
"""人裁写入的跨进程锁（2026-09-26，H 人裁单写者，任务书件 1）。

事件（`events.py`）、裁决表（`gold/store.py`）、排除名单／字形库体检裁决
（`consumers.py::route_and_consume`）都是「整读→改→整写」的读改写：并发时
两次写互相踩，已经真丢过数据（cv `9f1ea8c`「并发写会丢金标、撞事件号」；
ws `6f6cb846`「补回并发写丢的 9 条」）。控制台自己的 `_EVENTS_LOCK`
（`console/routers/feedback.py`）是 `threading.Lock`，只管控制台**这一个进程**——
CLI（`guji events route`／`guji gold import` 等）与脚本是另外的进程，天生管不到。

这里给的是同一把**跨进程**互斥量，实现抄 `core/runlock.py::_try_lock`
（flock／Windows `msvcrt.locking`），但**阻塞等**而不是抢不到就报错退出——
跑批锁保护的是几十分钟的整册跑批，抢不到就该报持有者退出；这里保护的是
毫秒级的「读文件→改内存→写文件」临界区，等一下就好，不该在这层加错误处理。

同进程内**可重入**（线程局部深度计数）：`route_and_consume` 整体包这把锁后，
内部再调 `EventLog.mark_consumed()`／`GoldStore.upsert()` 等同样包锁的方法，
不会对自己已经持有的锁死等。
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path

LOCK_NAME = ".write.lock"

_local = threading.local()


def _try_lock(fh, blocking: bool) -> bool:
    if os.name == "nt":
        import msvcrt
        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), mode, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return True
    except OSError:
        return False


def write_lock_path(root: Path | str) -> Path:
    return Path(root) / LOCK_NAME


@contextmanager
def feedback_write_lock(root: Path | str):
    """持锁期间独占「以 `root` 为根的这一份人裁共享状态」的写临界区。

    `root` 通常是 `feedback_root()`；裁决表（`feedback/verdicts`）是它的子目录，
    传同一个 `feedback_root()` 就与事件日志共用同一把锁——两者本就该互斥
    （一次 POST 常常是「写事件 → 立即消费进裁决表」一条链，見 `route_and_consume`）。
    排除名单 (`config/crop_exclusions.jsonl`) 与字形库体检裁决
    (`glyph_selfcheck/*.jsonl`) 物理路径不在 `feedback/` 下，但走
    `route_and_consume` 时一并在这把锁的临界区里——锁保护的是「互斥」，不要求
    锁文件与被保护的数据同目录。
    """
    path = write_lock_path(Path(root).resolve())
    held = getattr(_local, "held", None)
    if held is None:
        held = {}
        _local.held = held
    key = str(path)
    if held.get(key, 0) > 0:
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    try:
        _try_lock(fh, blocking=True)
        held[key] = 1
        try:
            yield
        finally:
            held[key] = 0
    finally:
        fh.close()   # 关闭即放锁
