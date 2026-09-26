# -*- coding: utf-8 -*-
"""`guji deploy check` 的五种情形：无更新／有锁／窗口外／健康检查失败回滚／成功。

全部用假 `git_runner` / `systemctl_runner` / `install_runner` / `http_get`——
不碰真 git 仓、真 systemd、真网络（`deploy_check` 本来就是为这个设计成处处
可注入，见 `ops/deploy_check.py` 模块头）。`--dry-run` 单独验证「不调用任何
会改状态的 runner」。
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from open_guji_cv.ops import deploy_check as dc


def _cp(stdout: str = "", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class FakeGit:
    """`{branch: rev}` 两条——本地 `production` 与 `origin/production`。调用记录在 `.calls`。"""

    def __init__(self, local_rev: str, remote_rev: str, *, fetch_ok: bool = True,
                merge_ok: bool = True):
        self.local_rev = local_rev
        self.remote_rev = remote_rev
        self.fetch_ok = fetch_ok
        self.merge_ok = merge_ok
        self.calls: list[list[str]] = []

    def __call__(self, repo: Path, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(args)
        if args[0] == "fetch":
            return _cp(returncode=0 if self.fetch_ok else 1, stderr="" if self.fetch_ok else "网络不通")
        if args[0] == "rev-parse" and args[1] == "production":
            return _cp(stdout=self.local_rev + "\n")
        if args[0] == "rev-parse" and args[1] == "origin/production":
            return _cp(stdout=self.remote_rev + "\n")
        if args[0] == "checkout":
            self.local_rev = args[1] if args[1] != "production" else self.local_rev
            return _cp()
        if args[0] == "merge":
            if self.merge_ok:
                self.local_rev = self.remote_rev
                return _cp()
            return _cp(returncode=1, stderr="冲突")
        return _cp()


def _no_lock(products_root):
    return []


@pytest.fixture
def no_sleep():
    return lambda seconds: None


def test_no_update_when_local_matches_remote(no_sleep):
    git = FakeGit(local_rev="abc123", remote_rev="abc123")
    result = dc.deploy_check(Path("/fake/repo"), git_runner=git, sleeper=no_sleep)
    assert result.status == dc.NO_UPDATE
    # 没有更新时不该去查锁、不该调 systemctl —— 只 fetch/rev-parse 了两次
    assert all(c[0] in ("fetch", "rev-parse") for c in git.calls)


def test_fetch_uses_explicit_refspec_not_bare_branch_name(no_sleep):
    """回归 2026-09-26 实测的坑：只传裸分支名，`git fetch` 更不更新
    `refs/remotes/<remote>/<branch>` 要看这个 checkout 配的 fetch refspec
    （这个仓的沙箱 clone 只配了 `+refs/heads/main:...`，production 传裸分支名
    fetch 完 `git rev-parse origin/production` 照样 unknown revision）——
    必须显式给目标端，不能依赖调用方的 remote 配置。"""
    git = FakeGit(local_rev="abc123", remote_rev="abc123")   # 无更新，fetch 之后立刻退出
    dc.deploy_check(Path("/fake/repo"), git_runner=git, sleeper=no_sleep)
    fetch_call = next(c for c in git.calls if c[0] == "fetch")
    assert fetch_call == ["fetch", "origin", "+production:refs/remotes/origin/production"]


def test_resolve_failed_when_rev_parse_errors(no_sleep):
    """`git rev-parse <解析不出的东西>` 会把参数原样回显到 stdout、真正的错误在
    stderr、退出码非零——不查 returncode 就会把这行回显误当成"新提交"（2026-09-26
    实测踩到的真 bug，见 `deploy_check.py` 里这段注释）。"""

    class BrokenGit(FakeGit):
        def __call__(self, repo, args):
            if args[0] == "rev-parse" and args[1] == "origin/production":
                self.calls.append(args)
                return _cp(stdout="origin/production\n", returncode=128,
                          stderr="fatal: ambiguous argument 'origin/production': unknown revision")
            return super().__call__(repo, args)

    git = BrokenGit(local_rev="abc123", remote_rev="def456")
    result = dc.deploy_check(Path("/fake/repo"), git_runner=git, sleeper=no_sleep)
    assert result.status == dc.RESOLVE_FAILED


def test_fetch_failed_short_circuits(no_sleep):
    git = FakeGit(local_rev="abc123", remote_rev="def456", fetch_ok=False)
    result = dc.deploy_check(Path("/fake/repo"), git_runner=git, sleeper=no_sleep)
    assert result.status == dc.FETCH_FAILED


def test_locked_when_a_book_holds_run_lock(tmp_path, no_sleep):
    products = tmp_path / "products"
    book_dir = products / "vol02"
    book_dir.mkdir(parents=True)
    lock_path = book_dir / ".run.lock"
    lock_path.write_text('{"pid": 4321, "host": "srv", "cmd": "guji pipeline …"}', encoding="utf-8")
    # 真占住这把锁（模拟另一个进程正在跑批）：本测试进程持有独占 flock 不放。
    import fcntl
    held_fh = open(lock_path, "r+", encoding="utf-8")
    fcntl.flock(held_fh, fcntl.LOCK_EX)
    try:
        git = FakeGit(local_rev="abc123", remote_rev="def456")
        result = dc.deploy_check(Path("/fake/repo"), products_root=products,
                                 git_runner=git, sleeper=no_sleep)
        assert result.status == dc.LOCKED
        assert result.detail["books"] == ["vol02"]
    finally:
        fcntl.flock(held_fh, fcntl.LOCK_UN)
        held_fh.close()


def test_no_lock_when_lock_file_stale(tmp_path, no_sleep):
    """锁文件存在但没人真的占着（上一次跑批正常退出留下的文件）——不该拦部署。"""
    products = tmp_path / "products"
    book_dir = products / "vol02"
    book_dir.mkdir(parents=True)
    (book_dir / ".run.lock").write_text('{"pid": 1, "host": "srv"}', encoding="utf-8")
    git = FakeGit(local_rev="abc123", remote_rev="def456")
    calls = {"install": 0, "restart": []}

    def install(repo):
        calls["install"] += 1
        return _cp()

    def systemctl(args):
        calls["restart"].append(args)
        return _cp()

    result = dc.deploy_check(Path("/fake/repo"), products_root=products, git_runner=git,
                             install_runner=install, systemctl_runner=systemctl,
                             http_get=lambda url: 200, sleeper=no_sleep)
    assert result.status == dc.DEPLOYED
    assert calls["install"] == 1


def test_outside_window_blocks_deploy(no_sleep):
    git = FakeGit(local_rev="abc123", remote_rev="def456")
    window = dc.DeployWindow(enabled=True, allowed_hours=((2, 4),))
    now = datetime(2026, 9, 26, 10, 0, tzinfo=timezone.utc)   # 10 点，不在 [2,4)
    result = dc.deploy_check(Path("/fake/repo"), git_runner=git, window=window, now=now,
                             sleeper=no_sleep)
    assert result.status == dc.OUTSIDE_WINDOW


def test_window_disabled_by_default_allows_any_time(no_sleep):
    git = FakeGit(local_rev="abc123", remote_rev="def456")
    now = datetime(2026, 9, 26, 10, 0, tzinfo=timezone.utc)
    result = dc.deploy_check(Path("/fake/repo"), git_runner=git, now=now,
                             install_runner=lambda repo: _cp(), systemctl_runner=lambda a: _cp(),
                             http_get=lambda url: 200, sleeper=no_sleep)
    assert result.status == dc.DEPLOYED


def test_health_check_failure_rolls_back(no_sleep):
    git = FakeGit(local_rev="abc123", remote_rev="def456")
    restarts = []

    def systemctl(args):
        restarts.append(args)
        return _cp()

    result = dc.deploy_check(Path("/fake/repo"), git_runner=git,
                             install_runner=lambda repo: _cp(), systemctl_runner=systemctl,
                             http_get=lambda url: 500, sleeper=no_sleep)
    assert result.status == dc.ROLLED_BACK
    assert result.detail["rolled_back_to"] == "abc123"
    # 回滚：checkout 回旧提交、再重启一次——总共两次 restart（部署时一次、回滚后一次）
    assert len(restarts) == 2
    checkout_targets = [c[1] for c in git.calls if c[0] == "checkout"]
    assert "abc123" in checkout_targets


def test_deployed_when_healthy(no_sleep):
    git = FakeGit(local_rev="abc123", remote_rev="def456")
    result = dc.deploy_check(Path("/fake/repo"), git_runner=git,
                             install_runner=lambda repo: _cp(), systemctl_runner=lambda a: _cp(),
                             http_get=lambda url: 200, sleeper=no_sleep)
    assert result.status == dc.DEPLOYED
    assert result.detail == {"from_rev": "abc123", "to_rev": "def456"}


def test_dry_run_touches_nothing(no_sleep):
    git = FakeGit(local_rev="abc123", remote_rev="def456")
    calls = {"install": 0, "systemctl": 0, "http": 0}

    def install(repo):
        calls["install"] += 1
        return _cp()

    def systemctl(args):
        calls["systemctl"] += 1
        return _cp()

    def http(url):
        calls["http"] += 1
        return 200

    result = dc.deploy_check(Path("/fake/repo"), git_runner=git, install_runner=install,
                             systemctl_runner=systemctl, http_get=http, sleeper=no_sleep,
                             dry_run=True)
    assert result.status == dc.WOULD_DEPLOY
    assert calls == {"install": 0, "systemctl": 0, "http": 0}
    # dry-run 只应该 fetch/rev-parse 过，不该 checkout/merge
    assert all(c[0] in ("fetch", "rev-parse") for c in git.calls)


# ── 部署记录与夜间重算队列 ───────────────────────────────────────────
def test_write_deploy_record_writes_markdown_without_pushing(tmp_path):
    overview = tmp_path / "overview"
    overview.mkdir()
    result = dc.DeployResult(dc.DEPLOYED, {"from_rev": "abc", "to_rev": "def"})
    path = dc.write_deploy_record(overview, result, stale_summary={"vol02": ["glyph_match"]},
                                  push=False)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "deployed" in text
    assert "vol02" in text
    assert "glyph_match" in text
