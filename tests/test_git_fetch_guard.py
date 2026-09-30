# -*- coding: utf-8 -*-
"""自动部署／snap-watch 的 fetch 护栏（`ops/git_fetch.py`，overview #236）：真 git、假 origin。

09-28 事故：服务器 cv 仓是浅克隆，`guji deploy check` 与 snap-watch 做不带 `--depth` 的
fetch，去拉整个仓的历史（约 4.7 GB），卡了近 7 小时。这里用本地浅克隆夹具断言：

- 浅仓的 fetch 带 `--depth`，拉完仍是浅仓、只多几十个提交；完整仓不带、不被改浅；
- production 一次前移超过 `--depth` 层时，部署会加深一次再快进，不退回拉全量；
- fetch 超时整组杀掉、返回 `reason=timeout`；盘余量不够不 fetch、返回 `reason=disk_low`；
- 被杀的 fetch 留下的 `tmp_pack_*` 会删掉；
- snap `check_cv` 在浅 cv 仓里能认出落在浅边界下面的老祖先，补拉提交也带 `--depth`。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from open_guji_cv.ops import deploy_check as dc
from open_guji_cv.ops import git_fetch as gf
from open_guji_cv.snap import gitio
from open_guji_cv.snap import importer as imp


def git(cwd: Path, *args: str) -> str:
    cp = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    return cp.stdout.strip()


def _commits(repo: Path, n: int, tag: str) -> None:
    """在当前分支上接 n 个空提交（fast-import，一千个也不到一秒）。"""
    parent = subprocess.run(["git", "rev-parse", "-q", "--verify", "HEAD"], cwd=repo,
                            capture_output=True, text=True).stdout.strip()
    branch = git(repo, "symbolic-ref", "HEAD")
    lines = []
    for i in range(n):
        msg = f"{tag}{i}".encode()
        lines.append(f"commit {branch}\nmark :{i + 1}\n"
                     f"committer t <t@t> {1_700_000_000 + i} +0000\ndata {len(msg)}\n")
        lines.append(msg.decode() + "\n")
        if i == 0 and parent:
            lines.append(f"from {parent}\n")
        lines.append("\n")
    subprocess.run(["git", "fast-import", "--quiet"], cwd=repo, input="".join(lines).encode(),
                   check=True, capture_output=True)
    git(repo, "reset", "-q", "--hard", branch)


@pytest.fixture(autouse=True)
def _no_disk_floor(monkeypatch):
    # 缺省门槛 10 GiB 是给服务器的；测试机盘小不该因此红。查盘分支单独用 free_fn 测。
    monkeypatch.setenv("GUJI_FETCH_MIN_FREE_GB", "0")


@pytest.fixture
def origin(tmp_path):
    """假 GitHub：`production` 分支上 1000 个提交——比部署加深后的 500 层与 check_cv 的
    `--deepen 200` 都深，拉完仍应是浅仓（历史太短的话加深会一路拉到根、仓自动变完整）。"""
    o = tmp_path / "origin"
    o.mkdir()
    git(o, "init", "-q", "-b", "production")
    git(o, "config", "user.email", "t@t")
    git(o, "config", "user.name", "t")
    _commits(o, 1000, "base")
    return o


def _clone(origin: Path, dest: Path, *, shallow: bool) -> Path:
    depth = ["--depth", "1"] if shallow else []
    subprocess.run(["git", "clone", "-q", *depth, "-b", "production", f"file://{origin}", str(dest)],
                   check=True, capture_output=True)
    return dest


class Recorder:
    """包一层真 runner，记下每次调用的参数。"""

    def __init__(self, inner):
        self.inner = inner
        self.calls: list[list[str]] = []

    def __call__(self, repo, args, *a, **k):
        self.calls.append(list(args))
        return self.inner(repo, args, *a, **k)

    def fetches(self):
        return [c for c in self.calls if c and c[0] == "fetch"]


def _ok(*a, **k):
    return subprocess.CompletedProcess([], 0, "", "")


# ── deploy check ─────────────────────────────────────────────────────
def test_deploy_fetch_on_shallow_clone_uses_depth(origin, tmp_path):
    server = _clone(origin, tmp_path / "server", shallow=True)
    _commits(origin, 3, "new")
    head = git(origin, "rev-parse", "HEAD")
    fetch = Recorder(gf.guarded_git_runner())
    res = dc.deploy_check(server, dry_run=True, git_runner=dc.default_git_runner, fetch_runner=fetch)
    assert res.status == dc.WOULD_DEPLOY and res.detail["to_rev"] == head
    assert fetch.fetches() == [["fetch", "--depth", str(gf.DEFAULT_DEPTH), "origin",
                                "+production:refs/remotes/origin/production"]]
    assert git(server, "rev-parse", "--is-shallow-repository") == "true"
    # 只拉了 depth 层，没把 1000 个 base 提交全拉下来
    assert int(git(server, "rev-list", "--count", "origin/production")) <= gf.DEFAULT_DEPTH


def test_deploy_fetch_on_full_clone_has_no_depth_and_stays_full(origin, tmp_path):
    server = _clone(origin, tmp_path / "server", shallow=False)
    _commits(origin, 2, "new")
    fetch = Recorder(gf.guarded_git_runner())
    res = dc.deploy_check(server, dry_run=True, git_runner=dc.default_git_runner, fetch_runner=fetch)
    assert res.status == dc.WOULD_DEPLOY
    assert all("--depth" not in c for c in fetch.fetches())
    assert git(server, "rev-parse", "--is-shallow-repository") == "false"


def test_deploy_deepens_when_production_jumped_past_depth(origin, tmp_path):
    """production 一次前移 80 个提交（> depth 50）：浅拉 50 层接不上本地分支，
    要加深一次再 `merge --ff-only`，而不是 MERGE_FAILED 或退回拉全量。"""
    server = _clone(origin, tmp_path / "server", shallow=True)
    _commits(origin, 80, "jump")
    head = git(origin, "rev-parse", "HEAD")
    fetch = Recorder(gf.guarded_git_runner())
    res = dc.deploy_check(server, git_runner=dc.default_git_runner, fetch_runner=fetch,
                          install_runner=_ok, systemctl_runner=_ok, http_get=lambda url: 200,
                          sleeper=lambda s: None)
    assert res.status == dc.DEPLOYED, res.to_dict()
    assert git(server, "rev-parse", "production") == head
    depths = [c[c.index("--depth") + 1] for c in fetch.fetches()]
    assert depths == [str(gf.DEFAULT_DEPTH), str(gf.DEFAULT_DEPTH * 10)]
    assert git(server, "rev-parse", "--is-shallow-repository") == "true"


def test_deploy_fetch_timeout_aborts(origin, tmp_path):
    server = _clone(origin, tmp_path / "server", shallow=True)
    _commits(origin, 1, "new")
    # 假 origin 的 upload-pack 先睡 60 秒，模拟「服务端在打 4.7 GB 的包」
    git(server, "config", "remote.origin.uploadpack", "sleep 60; git-upload-pack")
    t0 = time.time()
    res = dc.deploy_check(server, dry_run=True, git_runner=dc.default_git_runner,
                          fetch_runner=gf.guarded_git_runner(timeout=1.5))
    assert time.time() - t0 < 20
    assert res.status == dc.FETCH_FAILED and res.detail["reason"] == gf.GUARD_TIMEOUT
    assert "超过" in res.detail["stderr"]


def test_deploy_fetch_refuses_when_disk_low(origin, tmp_path):
    server = _clone(origin, tmp_path / "server", shallow=True)
    before = git(server, "rev-parse", "origin/production")
    _commits(origin, 1, "new")
    res = dc.deploy_check(server, dry_run=True, git_runner=dc.default_git_runner,
                          fetch_runner=gf.guarded_git_runner(min_free_gb=10, free_fn=lambda p: 1 << 30))
    assert res.status == dc.FETCH_FAILED and res.detail["reason"] == gf.GUARD_DISK_LOW
    assert git(server, "rev-parse", "origin/production") == before   # 没 fetch


def test_default_runner_routes_fetch_through_guard(origin, tmp_path, monkeypatch):
    """不注入 fetch_runner 时，真 git 的 fetch 也要走护栏（CLI 就是这么调的）。"""
    server = _clone(origin, tmp_path / "server", shallow=True)
    monkeypatch.setenv("GUJI_FETCH_MIN_FREE_GB", "1000000")
    res = dc.deploy_check(server, dry_run=True)
    assert res.status == dc.FETCH_FAILED and res.detail["reason"] == gf.GUARD_DISK_LOW


# ── run_guarded 本身 ───────────────────────────────────────────────────
def test_timeout_kills_process_group_and_removes_tmp_packs(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    pack_dir = repo / ".git" / "objects" / "pack"
    old = pack_dir / "tmp_pack_old"
    old.write_bytes(b"x")                       # 开跑前就在的，不许删
    past = time.time() - 3600
    import os
    os.utime(old, (past, past))
    child = ("import pathlib, subprocess, sys, time;"
             f"pathlib.Path({str(pack_dir / 'tmp_pack_new')!r}).write_bytes(b'y'*1024);"
             # 再起一个孙进程，验证整组都被杀
             "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
             "time.sleep(60)")
    t0 = time.time()
    cp = gf.run_guarded(repo, ["fetch"], timeout=1.0, poll=0.2, min_free_bytes=0,
                        argv0=[sys.executable, "-c", child, "--"])
    assert time.time() - t0 < 15
    assert gf.guard_reason(cp) == gf.GUARD_TIMEOUT and cp.returncode != 0
    assert not (pack_dir / "tmp_pack_new").exists()
    assert old.exists()


def test_disk_watchdog_aborts_mid_fetch(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    frees = iter([100, 100, 0, 0, 0, 0, 0, 0])   # 开跑前够，跑着跑着没了
    cp = gf.run_guarded(repo, ["fetch"], timeout=30, poll=0.2, min_free_bytes=50,
                        free_fn=lambda p: next(frees, 0),
                        argv0=[sys.executable, "-c", "import time; time.sleep(60)", "--"])
    assert gf.guard_reason(cp) == gf.GUARD_DISK_LOW


def test_fetch_args():
    assert gf.fetch_args("origin", ["x"], shallow=False) == ["fetch", "origin", "x"]
    assert gf.fetch_args("origin", ["x"], shallow=True, depth=7, quiet=True) == \
        ["fetch", "-q", "--depth", "7", "origin", "x"]


# ── snap：check_cv 与 fetch_branches ─────────────────────────────────
def test_check_cv_on_shallow_repo_finds_old_ancestor(origin, tmp_path):
    """包的 cv 是服务器 HEAD 的老祖先、落在浅边界下面：先 `--deepen` 再判，判成兼容；
    不许退回不带 depth 的 fetch。"""
    old = git(origin, "rev-parse", "HEAD~40")
    cv = _clone(origin, tmp_path / "cv", shallow=True)
    rec = Recorder(gitio.default_git)
    ok, detail = imp.check_cv(cv, {"cv": {"commit": old}}, git=rec)
    assert ok, detail
    for c in rec.fetches():
        assert any(a == "--depth" or a.startswith("--deepen") for a in c), c
    assert git(cv, "rev-parse", "--is-shallow-repository") == "true"


def test_check_cv_fetches_newer_commit_with_depth(origin, tmp_path):
    """包的 cv 比服务器 HEAD 新（服务器还没部署到）：补拉那个提交要带 depth，判不兼容。"""
    cv = _clone(origin, tmp_path / "cv", shallow=True)
    _commits(origin, 5, "later")
    newer = git(origin, "rev-parse", "HEAD")
    rec = Recorder(gitio.default_git)
    ok, detail = imp.check_cv(cv, {"cv": {"commit": newer}}, git=rec)
    assert not ok and detail["checked"][newer] == "不是 HEAD 的祖先"
    commit_fetch = [c for c in rec.fetches() if newer in c]
    assert commit_fetch and "--depth" in commit_fetch[0]


def test_check_cv_on_full_repo_does_not_deepen(origin, tmp_path):
    cv = _clone(origin, tmp_path / "cv", shallow=False)
    _commits(origin, 2, "later")
    newer = git(origin, "rev-parse", "HEAD")
    rec = Recorder(gitio.default_git)
    imp.check_cv(cv, {"cv": {"commit": newer}}, git=rec)
    assert all("--depth" not in c and not any(a.startswith("--deepen") for a in c) for c in rec.fetches())
    assert git(cv, "rev-parse", "--is-shallow-repository") == "false"


def test_fetch_branches_timeout_raises(origin, tmp_path, monkeypatch):
    ws = _clone(origin, tmp_path / "ws", shallow=True)
    git(ws, "config", "remote.origin.uploadpack", "sleep 60; git-upload-pack")
    monkeypatch.setenv("GUJI_FETCH_TIMEOUT", "1.5")
    t0 = time.time()
    with pytest.raises(gitio.GitError, match="guard:timeout"):
        gitio.fetch_branches(ws, ["production"])
    assert time.time() - t0 < 20
