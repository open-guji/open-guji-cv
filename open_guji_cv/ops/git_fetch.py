# -*- coding: utf-8 -*-
"""服务器上所有自动 `git fetch` 共用的护栏（K 道，overview #236，2026-09-28）。

事故：服务器 cv 仓是浅克隆（`.git/shallow` 09-28 03:04Z 生成，边界 `b961082`）。浅仓做
**不带 `--depth` 的** fetch 时，新提交的历史接不上本地那一个浅边界，服务端就把整段历史
（GitHub 报仓库约 4.7 GB）打包发过来；临时 pack 堆到约 13 GB、盘一度只剩 27 G，自动部署
与 snap-watch 从 10:25Z 起卡了近 7 小时。

三道闸，都在这里：

1. **浅仓一律带 `--depth`**（`fetch_args`）：只看仓现在是不是浅的（`rev-parse
   --is-shallow-repository`）。**完整 clone 不带**——对完整 clone 带 `--depth` 会写
   `.git/shallow` 把它变浅（2026-09-27 实测），服务器 guji-workspace 还要给
   glyph_store_sync 推送，不能被悄悄改浅；完整仓的 fetch 协商得出共同历史，本来就不会拉全量。
2. **开跑前查盘**（`disk_free`）：余量低于门槛就不 fetch，返回 `reason=disk_low`。
3. **超时与盘余量看门狗**（`run_guarded`）：git 放进独立进程组跑，超时或跑的过程中余量
   跌破门槛就整组杀掉（`git fetch` 底下还挂着 `remote-https`／`index-pack` 子进程，
   只杀父进程它们会接着写），并删掉这次留下的 `objects/pack/tmp_pack_*`／`tmp_idx_*`
   （值守 09-28 是手工删的 13 GB）。

结果都是 `subprocess.CompletedProcess`，失败时 `returncode != 0`、`stderr` 首行写清
原因（`[guard:timeout]`／`[guard:disk_low]`），调用方不用认新类型。
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

#: 部署用的深度：值守 09-28 手动绕过用的就是 50，几秒拉完。
DEFAULT_DEPTH = 50


def default_timeout() -> float:
    """单次 fetch 超时（秒），环境变量 `GUJI_FETCH_TIMEOUT` 可改。正常增量 fetch 几秒；
    10 分钟还没完就是在拉全量。调用时才读，改环境变量不用重启进程。"""
    return float(os.environ.get("GUJI_FETCH_TIMEOUT", "600"))


def default_min_free_gb() -> float:
    """fetch 开跑前与跑的过程中，仓所在盘至少要留的余量（GiB），`GUJI_FETCH_MIN_FREE_GB`
    可改。服务器平时剩 40 G 上下，09-28 事故最低到 27 G。"""
    return float(os.environ.get("GUJI_FETCH_MIN_FREE_GB", "10"))

GUARD_TIMEOUT = "timeout"
GUARD_DISK_LOW = "disk_low"
_GUARD_RC = {GUARD_TIMEOUT: 124, GUARD_DISK_LOW: 125}


def guard_reason(cp: subprocess.CompletedProcess) -> str | None:
    """这次失败是不是护栏拦下的：返回 `timeout`／`disk_low`，否则 None。"""
    err = cp.stderr if isinstance(cp.stderr, str) else (cp.stderr or b"").decode("utf-8", "replace")
    for reason in _GUARD_RC:
        if err.startswith(f"[guard:{reason}]"):
            return reason
    return None


def _guard_fail(args: list[str], reason: str, msg: str) -> subprocess.CompletedProcess:
    print(f"[git_fetch] {reason}: {msg}", file=sys.stderr)
    return subprocess.CompletedProcess(args, _GUARD_RC[reason], "", f"[guard:{reason}] {msg}")


def disk_free(path: Path) -> int:
    """`path` 所在盘的可用字节；路径不存在就往上找存在的祖先。"""
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def is_shallow(repo: Path, git: Callable[..., subprocess.CompletedProcess]) -> bool:
    cp = git(repo, ["rev-parse", "--is-shallow-repository"])
    out = cp.stdout if isinstance(cp.stdout, str) else (cp.stdout or b"").decode()
    return cp.returncode == 0 and out.strip() == "true"


def fetch_args(remote: str, refspecs: list[str], *, shallow: bool, depth: int = DEFAULT_DEPTH,
               quiet: bool = False) -> list[str]:
    """拼 `git fetch` 参数。浅仓带 `--depth`，完整仓不带（见模块头第 1 条）。"""
    args = ["fetch"]
    if quiet:
        args.append("-q")
    if shallow:
        args += ["--depth", str(depth)]
    return [*args, remote, *refspecs]


def _git_dir(repo: Path) -> Path | None:
    cp = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=repo, capture_output=True, text=True)
    if cp.returncode != 0:
        return None
    d = Path(cp.stdout.strip())
    return d if d.is_absolute() else (Path(repo) / d)


def _clean_tmp_packs(repo: Path, since: float) -> list[str]:
    """删掉 `since` 之后生成的 `objects/pack/tmp_*`——被杀掉的 fetch 留下的半截 pack。"""
    gd = _git_dir(repo)
    if gd is None:
        return []
    gone = []
    for f in (gd / "objects" / "pack").glob("tmp_*"):
        try:
            if f.stat().st_mtime >= since - 1:
                f.unlink()
                gone.append(f.name)
        except OSError:
            pass
    return gone


def run_guarded(repo: Path, args: list[str], *, timeout: float | None = None,
                min_free_bytes: int | None = None, poll: float = 2.0,
                env: dict | None = None, text: bool = True,
                free_fn: Callable[[Path], int] = disk_free,
                argv0: list[str] | None = None) -> subprocess.CompletedProcess:
    """跑 `git <args>`（`argv0` 可换掉 `["git"]`，测试用），带查盘、超时、盘余量看门狗。"""
    repo = Path(repo)
    timeout = default_timeout() if timeout is None else timeout
    if min_free_bytes is None:
        min_free_bytes = int(default_min_free_gb() * (1 << 30))
    free = free_fn(repo)
    if free < min_free_bytes:
        return _guard_fail(args, GUARD_DISK_LOW,
                           f"开跑前盘余量 {free / (1 << 30):.1f} GiB < 门槛 {min_free_bytes / (1 << 30):.1f} GiB，"
                           f"不 fetch（{repo}）")
    full_env = {**os.environ, **env} if env else None
    # 不让 git 在终端上等密码（定时器下没人回答，会一直挂到超时）
    full_env = {**(full_env or os.environ), "GIT_TERMINAL_PROMPT": "0"}
    start = time.time()
    proc = subprocess.Popen([*(argv0 or ["git"]), *args], cwd=repo, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=text, env=full_env, start_new_session=True)
    reason = msg = None
    while True:
        try:
            out, err = proc.communicate(timeout=poll)
            return subprocess.CompletedProcess(args, proc.returncode, out, err)
        except subprocess.TimeoutExpired:
            pass
        elapsed = time.time() - start
        if elapsed >= timeout:
            reason, msg = GUARD_TIMEOUT, f"git {' '.join(args[:1])} 跑了 {elapsed:.0f}s 超过 {timeout:.0f}s"
        else:
            free = free_fn(repo)
            if free < min_free_bytes:
                reason, msg = GUARD_DISK_LOW, (f"跑的过程中盘余量跌到 {free / (1 << 30):.1f} GiB"
                                               f" < 门槛 {min_free_bytes / (1 << 30):.1f} GiB")
        if reason:
            break
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
    proc.communicate()
    gone = _clean_tmp_packs(repo, start)
    if gone:
        msg += f"；已删半截 pack {len(gone)} 个"
    return _guard_fail(args, reason, msg + f"，已中止（{repo}）")


def guarded_git_runner(*, timeout: float | None = None, min_free_gb: float | None = None,
                       free_fn: Callable[[Path], int] = disk_free):
    """给 `deploy_check`／`snap.gitio` 用的 runner：签名与它们的 `git_runner` 一样。
    不给的参数按调用时的环境变量取（见 `default_timeout`／`default_min_free_gb`）。"""
    def run(repo: Path, args: list[str], env: dict | None = None, binary: bool = False):
        mfb = None if min_free_gb is None else int(min_free_gb * (1 << 30))
        return run_guarded(repo, args, timeout=timeout, min_free_bytes=mfb,
                           env=env, text=not binary, free_fn=free_fn)
    return run
