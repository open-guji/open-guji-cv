# -*- coding: utf-8 -*-
"""快照收发用到的 git 调用。都走一个可注入的 `runner(repo, args, env=None, stdin=None)`，
跟 `ops/deploy_check.py` 同一套路：测试里换成对假 origin 的真 git，或纯假实现。"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

GitRunner = Callable[..., subprocess.CompletedProcess]


def default_git(repo: Path, args: list[str], env: dict | None = None,
                binary: bool = False) -> subprocess.CompletedProcess:
    full_env = None
    if env:
        full_env = {**os.environ, **env}
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=not binary, env=full_env)


def _ok(cp: subprocess.CompletedProcess, what: str) -> str:
    if cp.returncode != 0:
        err = cp.stderr if isinstance(cp.stderr, str) else (cp.stderr or b"").decode("utf-8", "replace")
        raise GitError(f"{what} 失败：{err.strip()[-500:]}")
    out = cp.stdout
    return out if isinstance(out, str) else out.decode("utf-8", "replace")


class GitError(RuntimeError):
    pass


def ls_remote_snaps(repo: Path, remote: str = "origin", git: GitRunner = default_git) -> dict[str, str]:
    """远端所有 `snap/*` 分支 → 提交 sha。"""
    out = _ok(git(repo, ["ls-remote", remote, "refs/heads/snap/*"]), "ls-remote")
    res = {}
    for line in out.splitlines():
        sha, _, ref = line.partition("\t")
        if ref.startswith("refs/heads/"):
            res[ref[len("refs/heads/"):]] = sha.strip()
    return res


def fetch_branches(repo: Path, branches: list[str], remote: str = "origin",
                   git: GitRunner = default_git) -> None:
    """显式 refspec 拉到 `refs/remotes/<remote>/<branch>`（裸分支名不可靠，见
    deploy_check 的注释）。

    ⚠️ **只在仓本来就是浅克隆时才加 `--depth 1`**：对完整 clone 带 `--depth` 拉，git 会写
    `.git/shallow`、把整个仓变成浅仓（2026-09-27 实测）——服务器上那份 guji-workspace 还要
    给 glyph_store_sync 提交推送用，不能被悄悄改成浅仓。孤儿包是无父单提交，带不带 depth
    传的东西一样。"""
    if not branches:
        return
    specs = [f"+refs/heads/{b}:refs/remotes/{remote}/{b}" for b in branches]
    shallow = git(repo, ["rev-parse", "--is-shallow-repository"]).stdout.strip() == "true"
    depth = ["--depth", "1"] if shallow else []
    _ok(git(repo, ["fetch", "-q", *depth, remote, *specs]), "fetch")


def remote_ref(branch: str, remote: str = "origin") -> str:
    return f"refs/remotes/{remote}/{branch}"


def rev_parse(repo: Path, rev: str, git: GitRunner = default_git) -> str | None:
    cp = git(repo, ["rev-parse", "--verify", "-q", f"{rev}^{{commit}}"])
    return cp.stdout.strip() if cp.returncode == 0 else None


def show_file(repo: Path, ref: str, path: str, git: GitRunner = default_git) -> str:
    return _ok(git(repo, ["show", f"{ref}:{path}"]), f"读 {ref}:{path}")


def archive_tar(repo: Path, ref: str, git: GitRunner = default_git) -> bytes:
    cp = git(repo, ["archive", "--format=tar", ref], binary=True)
    if cp.returncode != 0:
        raise GitError(f"git archive {ref} 失败：{(cp.stderr or b'').decode('utf-8', 'replace')[-300:]}")
    return cp.stdout


def is_ancestor(repo: Path, maybe_ancestor: str, rev: str = "HEAD", git: GitRunner = default_git) -> bool | None:
    """True/False；`maybe_ancestor` 在本地根本找不到时返回 None。"""
    if rev_parse(repo, maybe_ancestor, git) is None:
        return None
    return git(repo, ["merge-base", "--is-ancestor", maybe_ancestor, rev]).returncode == 0


def commit_tree_from_dir(repo: Path, tree_dir: Path, message: str, git: GitRunner = default_git) -> str:
    """把 `tree_dir` 整个目录做成一个**无父提交**（孤儿），不动 `repo` 的工作区与索引。
    用临时索引 + `--work-tree`；`add -f` 绕开仓里的 .gitignore（products/ 在书目录里是忽略的）。"""
    index = tree_dir.parent / (tree_dir.name + ".index")
    env = {"GIT_INDEX_FILE": str(index),
           "GIT_AUTHOR_NAME": os.environ.get("GIT_AUTHOR_NAME", "guji-snap"),
           "GIT_AUTHOR_EMAIL": os.environ.get("GIT_AUTHOR_EMAIL", "guji-snap@localhost"),
           "GIT_COMMITTER_NAME": os.environ.get("GIT_COMMITTER_NAME", "guji-snap"),
           "GIT_COMMITTER_EMAIL": os.environ.get("GIT_COMMITTER_EMAIL", "guji-snap@localhost")}
    try:
        _ok(git(repo, ["--work-tree", str(tree_dir), "add", "-f", "-A", "."], env=env), "add")
        tree = _ok(git(repo, ["write-tree"], env=env), "write-tree").strip()
        return _ok(git(repo, ["commit-tree", tree, "-m", message], env=env), "commit-tree").strip()
    finally:
        try:
            index.unlink()
        except OSError:
            pass


def push_commit(repo: Path, commit: str, branch: str, remote: str = "origin",
                git: GitRunner = default_git) -> None:
    """推到一条**新**分支；分支已存在就失败（不覆盖别人的包）。"""
    _ok(git(repo, ["push", "-q", remote, f"{commit}:refs/heads/{branch}"]), f"push {branch}")
