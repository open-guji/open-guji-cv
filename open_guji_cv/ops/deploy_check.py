# -*- coding: utf-8 -*-
"""`guji deploy check`：服务器定时器（每 15 分钟，`guji-deploy.timer`）跑，拉模式。

服务器只跟 `production` 分支（overview 总览/16 §三）：

1. `git fetch`，`production` 没前进 → 退出（`NO_UPDATE`）；
2. 有，但书级跑批锁（`core.runlock`）被谁占着 → 记「待部署」退出（`LOCKED`）；
   维护窗口现阶段**缺省关**（`DeployWindow(enabled=False)`，用户 09-26 定：平台
   未上线、更新会很频繁，不设节奏）；
3. 可以部署：`checkout production` → 装依赖 → 重启控制台 → 健康检查
   （`/` 与 `/healthz` 都要 200）→ 失败自动回滚到部署前的提交、重启、报告；
4. 成功后 `guji status` 各书，把过期步写进「夜间重算队列」清单（只写清单，
   不自动起跑批——见 `collect_stale_summary`）。

所有外部动作（git / systemctl / pip / http / sleep）都是可注入的 callable，
`--dry-run` 只读不写、什么都不调用到真正会改变系统状态的那些默认实现。
"""
from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

NO_UPDATE = "no_update"
FETCH_FAILED = "fetch_failed"
RESOLVE_FAILED = "resolve_failed"
LOCKED = "locked"
OUTSIDE_WINDOW = "outside_window"
WOULD_DEPLOY = "would_deploy"
MERGE_FAILED = "merge_failed"
ROLLED_BACK = "rolled_back"
KNOWN_BAD = "known_bad"
DEPLOYED = "deployed"


# ── 可注入的外部动作（默认实现是真家伙）───────────────────────────────
def default_git_runner(repo: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def default_systemctl_runner(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def default_install_runner(repo: Path) -> subprocess.CompletedProcess:
    # 用跑本脚本的解释器（2026-09-27 服务器实测：systemd 用户服务的 PATH 里没有 `python`，
    # 写死 "python" 直接 FileNotFoundError）。
    return subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."], cwd=repo,
                          capture_output=True, text=True)


def default_http_get(url: str, timeout: float = 5.0) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 — 只打本机地址
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:
        return 0


# ── 维护窗口：现阶段缺省关，可配（用户 09-26 定，见模块头）───────────
@dataclasses.dataclass
class DeployWindow:
    enabled: bool = False
    #: UTC 小时区间 `[(start, end)]`，含 start 不含 end；`enabled=False` 时不看这个字段。
    allowed_hours: tuple[tuple[int, int], ...] = ()

    def allows(self, now: datetime) -> bool:
        if not self.enabled:
            return True
        h = now.hour
        return any(s <= h < e for s, e in self.allowed_hours)


# ── 书级跑批锁：复用 core.runlock 的 flock 协议，只探测不占用 ─────────
@dataclasses.dataclass
class RunLockInfo:
    book: str
    holder: dict


def find_run_locks(products_root: Path) -> list[RunLockInfo]:
    """哪些书正持有跑批锁。`flock` 抢得到（非阻塞）就说明没人在跑，立刻放掉；
    抢不到才是「真有人在跑」——不能只看锁文件存不存在，那份文件跑完也不会删
    （`core.runlock.book_run_lock` 的注释：进程一死锁就放，但文件本身会留着）。"""
    from ..core.runlock import _try_lock, read_holder
    out: list[RunLockInfo] = []
    if not products_root.is_dir():
        return out
    for book_dir in sorted(p for p in products_root.iterdir() if p.is_dir()):
        lock_path = book_dir / ".run.lock"
        if not lock_path.exists():
            continue
        fh = open(lock_path, "a+", encoding="utf-8")
        try:
            if _try_lock(fh, blocking=False):
                continue  # 抢到了＝没人在跑
            out.append(RunLockInfo(book=book_dir.name, holder=read_holder(lock_path) or {}))
        finally:
            fh.close()
    return out


@dataclasses.dataclass
class DeployResult:
    status: str
    detail: dict = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"status": self.status, **self.detail}


def _load_state(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(path: Path | None, state: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def deploy_check(repo: Path, *, remote: str = "origin", branch: str = "production",
                 service: str = "guji-cv-console", base_url: str = "http://127.0.0.1:8640",
                 products_root: Path | None = None, dry_run: bool = False,
                 window: DeployWindow | None = None, now: datetime | None = None,
                 git_runner: Callable[[Path, list[str]], subprocess.CompletedProcess] = default_git_runner,
                 systemctl_runner: Callable[[list[str]], subprocess.CompletedProcess] = default_systemctl_runner,
                 install_runner: Callable[[Path], subprocess.CompletedProcess] = default_install_runner,
                 http_get: Callable[[str], int] = default_http_get,
                 sleeper: Callable[[float], None] = time.sleep,
                 health_paths: tuple[str, ...] = ("/", "/healthz"),
                 state_path: Path | None = None,
                 health_timeout: float = 90.0) -> DeployResult:
    """`state_path`（2026-09-27）：记「真正部署成功的提交」与「部署失败过的提交」。
    判有没有更新以它为准、不看本地分支——否则 git 已前进而装依赖／重启失败时，本地分支
    已等于远端，下一轮会判 `no_update`，控制台永远停在旧代码（服务器实测踩到）。
    不给则退回旧行为（看本地分支）。"""
    window = window or DeployWindow()
    now = now or datetime.now(timezone.utc)

    # 显式给目标 refspec（`+<branch>:refs/remotes/<remote>/<branch>`），不能只传
    # 裸分支名——`git fetch <remote> <branch>` 认不认 `refs/remotes/<remote>/<branch>`
    # 取决于这个 checkout 配置的 fetch refspec，只有它匹配 `<branch>` 时才会更新那个
    # 远程跟踪引用，否则只落 `FETCH_HEAD`（2026-09-26 实测：这个仓的 clone 只配了
    # `+refs/heads/main:refs/remotes/origin/main`，`git fetch origin production`
    # 跑完 `git rev-parse origin/production` 照样 unknown revision——服务器上按什么
    # 方式 clone 不该影响这条逻辑对不对，显式给目标端才是可靠的）。
    # 浅克隆（服务器 cv 仓 09-28 起是浅仓）不带 --depth 的 fetch 协商不出共同历史，会去拉
    # 整仓历史（GitHub 报 ~4.7 GB），卡 6 小时、临时 pack 堆到 13 GB（值守 overview#216）。
    # 只在本来就是浅仓时加 depth——对完整 clone 带 --depth 会把它悄悄变成浅仓（见 snap/gitio）。
    shallow = (git_runner(repo, ["rev-parse", "--is-shallow-repository"]).stdout or "").strip() == "true"
    depth = ["--depth", "200"] if shallow else []
    fetch = git_runner(repo, ["fetch", *depth, remote, f"+{branch}:refs/remotes/{remote}/{branch}"])
    if fetch.returncode != 0:
        return DeployResult(FETCH_FAILED, {"stderr": fetch.stderr.strip()})

    local = git_runner(repo, ["rev-parse", branch])
    remote_rev = git_runner(repo, ["rev-parse", f"{remote}/{branch}"])
    # `git rev-parse <解析不出的东西>` 会把参数原样回显到 stdout、错误信息才在
    # stderr、退出码非零（2026-09-26 实测踩到：不查 returncode 时把这行回显字符串
    # 误当成"新提交"，报了个假的 `would_deploy`）——两边都要查 returncode。
    if local.returncode != 0 or remote_rev.returncode != 0:
        return DeployResult(RESOLVE_FAILED, {
            "local_stderr": local.stderr.strip(), "remote_stderr": remote_rev.stderr.strip()})
    local_rev, remote_head = local.stdout.strip(), remote_rev.stdout.strip()
    state = _load_state(state_path)
    deployed_rev = state.get("deployed") or local_rev
    if deployed_rev == remote_head:
        return DeployResult(NO_UPDATE, {"rev": deployed_rev})
    if state.get("failed") == remote_head:
        return DeployResult(KNOWN_BAD, {"rev": remote_head, "deployed": deployed_rev,
                                        "reason": state.get("failed_reason", "")})

    # 锁在「有没有更新」之后查——没更新时压根不用管有没有人在跑批。
    locks = find_run_locks(products_root) if products_root else []
    if locks:
        return DeployResult(LOCKED, {"books": [l.book for l in locks],
                                     "holders": {l.book: l.holder for l in locks},
                                     "target_rev": remote_head})

    if not window.allows(now):
        return DeployResult(OUTSIDE_WINDOW, {"now": now.isoformat(), "target_rev": remote_head})

    if dry_run:
        return DeployResult(WOULD_DEPLOY, {
            "from_rev": local_rev, "to_rev": remote_head,
            "plan": [f"git checkout {branch}", f"git merge --ff-only {remote}/{branch}",
                    "pip install -e .", f"systemctl --user restart {service}",
                    "健康检查 " + "、".join(base_url.rstrip('/') + p for p in health_paths)]})

    prev_rev = deployed_rev
    git_runner(repo, ["checkout", branch])
    merged = git_runner(repo, ["merge", "--ff-only", f"{remote}/{branch}"])
    if merged.returncode != 0:
        return DeployResult(MERGE_FAILED, {"stderr": merged.stderr.strip(), "target_rev": remote_head})

    def _rollback(reason: str) -> DeployResult:
        # 本地分支退回上一个部署成功的提交，再装一次、重启；失败提交记进状态，
        # 下一轮不再反复撞同一个坏提交（production 前进到新提交会自动再试）。
        git_runner(repo, ["checkout", "-B", branch, prev_rev])
        try:
            install_runner(repo)
        except Exception:  # noqa: BLE001 —— 回滚路上尽力而为
            pass
        systemctl_runner(["restart", service])
        _save_state(state_path, {"deployed": prev_rev, "failed": remote_head,
                                 "failed_reason": reason})
        return DeployResult(ROLLED_BACK, {"failed_rev": remote_head, "rolled_back_to": prev_rev,
                                          "reason": reason, "health_paths": list(health_paths)})

    try:
        inst = install_runner(repo)
    except Exception as e:  # noqa: BLE001
        return _rollback(f"install: {type(e).__name__}: {e}")
    if getattr(inst, "returncode", 0) not in (0, None):
        return _rollback("install: " + (getattr(inst, "stderr", "") or "")[-500:].strip())
    systemctl_runner(["restart", service])
    # 控制台冷启动要十几秒（导入 torch 等）；只等 2 秒就判失败会误回滚
    # （2026-09-27 服务器首次自动部署实测）。每 3 秒试一次，最多 health_timeout 秒。
    ok = False
    waited = 0.0
    while True:
        sleeper(3.0)
        waited += 3.0
        if all(http_get(base_url.rstrip("/") + p) == 200 for p in health_paths):
            ok = True
            break
        if waited >= health_timeout:
            break
    if not ok:
        return _rollback(f"health check (waited {waited:.0f}s)")

    _save_state(state_path, {"deployed": remote_head})
    return DeployResult(DEPLOYED, {"from_rev": prev_rev, "to_rev": remote_head})


# ── 部署成功之后：各书过期步 → 夜间重算队列清单（只写清单，不自动起跑批）───
def collect_stale_summary(workspace: Path, *, pages: str = "all") -> dict[str, list[str]]:
    """每本书哪些步有非新鲜产物（stale/missing）。一本书算失败不拖累别的书。

    **display-only 快照导进来的步一律不进队列**（2026-09-27，K 快照自动导入）：那些步
    是云端算好只给人看的（如全唐文关 context 的 Step1–7），指纹含云端的库/参数，在服务器上
    必然判过期——重算就把人要看的那份冲掉了。标记在 `products/<book>/.snap_marks.json`，
    由 `guji snap import` 写、下一个 replace-steps 包导入同一步时清。"""
    import os

    from ..core.book import list_books, load_book
    from ..core.engine import Engine, MISSING, STALE
    from ..core.pipeline import default_pipeline_id, load_pipeline
    from ..core.workspace import products_root
    from ..snap.manifest import display_only_steps
    os.environ["GUJI_WORKSPACE"] = str(workspace)
    out: dict[str, list[str]] = {}
    for bid in list_books(workspace / "books"):
        try:
            book = load_book(bid, workspace / "books")
            pl = load_pipeline(default_pipeline_id(book))
            eng = Engine(book, pl, log=lambda s: None)
            st = eng.status(pages=book.resolve_pages(pages))
            skip = display_only_steps(products_root(), bid)
            stale = [sid for sid, d in st["steps"].items()
                    if sid not in skip and (d["counts"].get(STALE, 0) or d["counts"].get(MISSING, 0))]
            if stale:
                out[bid] = stale
        except Exception as e:  # noqa: BLE001 —— 一本书读不出不拖累别的书
            out[bid] = [f"ERROR: {type(e).__name__}: {e}"]
    return out


def write_deploy_record(overview_repo: Path, result: DeployResult, *,
                        stale_summary: dict[str, list[str]] | None = None, push: bool = True,
                        git_runner: Callable[[Path, list[str]], subprocess.CompletedProcess]
                        = default_git_runner) -> Path:
    """写一张部署记录到 overview 仓 `进度/图片初步数字化/进度/inbox/部署/`，
    CV 总管的 `Monitor` 扫得到（overview 总览/16 §3.3 第 5 步）。"""
    ts = time.strftime("%Y%m%d-%H%M", time.gmtime())
    out_dir = overview_repo / "项目进展/图片初步数字化/进度/inbox/部署"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{ts}-deploy.md"
    lines = [f"# 部署记录 {ts}（UTC）", "", f"- 状态：`{result.status}`"]
    for k, v in result.detail.items():
        lines.append(f"- {k}：{v}")
    if stale_summary:
        lines += ["", "## 过期步排进夜间重算队列（只写清单，不自动起跑批）", ""]
        lines += [f"- {book}：{', '.join(steps)}" for book, steps in sorted(stale_summary.items())]
    elif result.status == DEPLOYED:
        lines += ["", "## 过期步排进夜间重算队列", "", "- （没配 workspace，跳过——见 done 单）"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if push:
        rel = str(path.relative_to(overview_repo))
        git_runner(overview_repo, ["add", "--", rel])
        commit = git_runner(overview_repo, ["commit", "-q", "-m", f"部署记录 {ts}", "--", rel])
        if commit.returncode == 0:
            for _ in range(2):
                git_runner(overview_repo, ["pull", "-q", "--rebase", "--autostash"])
                pushed = git_runner(overview_repo, ["push", "-q"])
                if pushed.returncode == 0:
                    break
    return path
