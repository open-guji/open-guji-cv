"""执行方「为什么没了」的痕迹：存活时间戳 + 退出原因。

执行方进程有时会凭空消失（云端 VM 暂停或回收、被外部杀），日志里看不出原因。这里做两件事：
1. 每 ALIVE_S 秒在 ``alive`` 文件里写一行「alive <时间> pid <号>」。下次上线时读到上一行，
   若不是正常退出，就报「上次存活到 X，距今 Y」——间隔很长、且别的执行方同时断档，多半是整机暂停。
2. SIGTERM／SIGINT 收到时先写日志再退出（SIGHUP 只在没被 nohup 忽略时处理）；正常退出、异常退出都在
   ``alive`` 里追加一行「exit <时间> <原因>」。SIGKILL、整机回收写不了任何东西，只能靠第 1 点推断。

所有写入都包在 try 里：磁盘满、写不进去时只是不记，不影响领单。
"""
from __future__ import annotations

import atexit
import os
import signal
import threading
import time
from pathlib import Path

ALIVE_S = 60
#: 上次存活距今超过这么久，才报「上次存活到…」（轮询间隔 30 秒，正常情况下每一拍都会写）
GAP_REPORT_S = 180

_state: dict = {"why": None, "stop": None}


def _fmt(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(ts))


def _append(path: Path, line: str) -> None:
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def last_record(path: Path) -> tuple[str, float, str] | None:
    """读上一条记录：(kind, 时间戳, 其余内容)；没有或读不了返回 None。kind 是 alive 或 exit。"""
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    except OSError:
        return None
    if not lines:
        return None
    parts = lines[-1].split(" ", 2)
    try:
        ts = float(parts[1])
    except (IndexError, ValueError):
        return None
    return parts[0], ts, parts[2] if len(parts) > 2 else ""


def start(home: Path, say=print, *, now: float | None = None) -> Path:
    """上线时调用：报上一条记录，装信号处理，起存活线程。返回 alive 文件路径。"""
    now = time.time() if now is None else now
    _state.update(why=None, stop=None)
    path = home / "alive"
    prev = last_record(path)
    if prev is not None:
        kind, ts, rest = prev
        gap = now - ts
        if kind == "exit":
            say(f"上次退出原因：{rest}（{_fmt(ts)}）")
        elif gap > GAP_REPORT_S:
            say(f"上次存活到 {_fmt(ts)}（距今 {gap / 60:.0f} 分钟），没有退出记录：进程被杀或整机暂停/回收")
    _append(path, f"start {now:.0f} pid {os.getpid()}")
    _install_signals(say)
    atexit.register(_at_exit, path, say)
    _alive_thread(path)
    return path


def _install_signals(say) -> None:
    def handler(signum, _frame):
        name = signal.Signals(signum).name
        _state["why"] = f"收到 {name}"
        say(f"[退出] 收到 {name}（pid {os.getpid()}），写完日志退出")
        raise SystemExit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, handler)
        except (OSError, ValueError):
            pass
    # nohup 起的进程 SIGHUP 是 SIG_IGN；覆盖它就等于让挂断杀掉执行方，所以只在默认处理时装
    try:
        if signal.getsignal(signal.SIGHUP) == signal.SIG_DFL:
            signal.signal(signal.SIGHUP, handler)
    except (OSError, ValueError):
        pass


def _alive_thread(path: Path) -> None:
    def loop():
        while True:
            time.sleep(ALIVE_S)
            _append(path, f"alive {time.time():.0f} pid {os.getpid()}")

    threading.Thread(target=loop, name="alive", daemon=True).start()


def note_exit(path: Path, why: str) -> None:
    """正常退出或异常退出时调用（只写一次）。"""
    if _state["stop"]:
        return
    _state["stop"] = why
    _append(path, f"exit {time.time():.0f} {why}")


def _at_exit(path: Path, say) -> None:
    note_exit(path, _state["why"] or "正常返回或未捕获异常（atexit）")


def mark_reason(why: str) -> None:
    """记下退出原因（runner 循环外层捕获到异常时调用）；没设过才记。"""
    if not _state["why"]:
        _state["why"] = why
