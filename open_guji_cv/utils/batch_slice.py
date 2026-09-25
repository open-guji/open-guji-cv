"""跑批自动进 guji-batch.slice（Linux 服务器上的共用内存额度）。

云服务器只有 7.5G，整条 OCR 流程一跑就 2–3G，曾多次把整机拖进 OOM、连带杀掉控制台。
装过 overview/scripts/srvmon/install.sh 的机器上有 `guji-batch.slice`（MemoryMax 3.5G）；
CLI 跑批入口一开头调 `enter_batch_slice()`，用 systemd-run 把**自己**原地 exec 进去
（pid、stdio、Ctrl-C 都不变），超额只杀跑批，不殃及控制台和别的会话。

没装切片的机器（Windows、本地 WSL、CI）什么都不做。`GUJI_NO_BATCH_SLICE=1` 可关。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

SLICE = "guji-batch.slice"

# 常驻的 Web 服务和秒回的查询不进切片
EXEMPT = {"console", "ui", "review", "status", "cache", "show-profile"}


def _first_command(argv: list[str]) -> str | None:
    skip = False
    for a in argv:
        if skip:
            skip = False
            continue
        if a in ("-o", "--output"):
            skip = True
            continue
        if a.startswith("-"):
            continue
        return a
    return None


def enter_batch_slice(argv: list[str]) -> None:
    if os.name != "posix" or os.environ.get("GUJI_NO_BATCH_SLICE") or os.environ.get("GUJI_IN_BATCH_SLICE"):
        return
    cmd = _first_command(argv)
    if cmd is None or cmd in EXEMPT:
        return
    if not (Path.home() / ".config/systemd/user" / SLICE).exists():
        return
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime or not (Path(runtime) / "bus").exists():
        return
    try:
        if SLICE in Path("/proc/self/cgroup").read_text():
            return
    except OSError:
        return
    systemd_run = shutil.which("systemd-run")
    if not systemd_run:
        return
    os.environ["GUJI_IN_BATCH_SLICE"] = "1"
    unit = f"guji-{cmd}-{os.getpid()}"
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(systemd_run, [systemd_run, "--user", "--scope", "--quiet", "--collect",
                           f"--slice={SLICE}", f"--unit={unit}", "--",
                           sys.executable, *sys.orig_argv[1:]])
