# -*- coding: utf-8 -*-
"""快照收发用到的 git 调用。都走一个可注入的 `runner(repo, args, env=None, stdin=None)`，
跟 `ops/deploy_check.py` 同一套路：测试里换成对假 origin 的真 git，或纯假实现。"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

from ..ops import git_fetch as _gf

GitRunner = Callable[..., subprocess.CompletedProcess]


def default_git(repo: Path, args: list[str], env: dict | None = None,
                binary: bool = False) -> subprocess.CompletedProcess:
    if args and args[0] == "fetch":
        # 所有 fetch 走护栏：超时整组杀、开跑前与跑的过程中查盘（overview #236）
        return _gf.run_guarded(repo, args, env=env, text=not binary)
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
    return ls_remote_heads(repo, "snap/*", remote, git)


def ls_remote_heads(repo: Path, pattern: str, remote: str = "origin",
                    git: GitRunner = default_git) -> dict[str, str]:
    """远端 `refs/heads/<pattern>` 的分支 → 提交 sha（`snap/*` 快照包、`idx/*` 模板索引）。"""
    out = _ok(git(repo, ["ls-remote", remote, f"refs/heads/{pattern}"]), "ls-remote")
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
    shallow = _gf.is_shallow(repo, git)
    _ok(git(repo, _gf.fetch_args(remote, specs, shallow=shallow, depth=1, quiet=True)), "fetch")


def fetch_commit(repo: Path, commit: str, remote: str = "origin", git: GitRunner = default_git,
                 depth: int = _gf.DEFAULT_DEPTH) -> subprocess.CompletedProcess:
    """按提交号拉一个提交（`check_cv` 用：服务器 cv 落后于包的 cv 时补拉）。

    浅仓带 `--depth`——09-28 服务器 cv 是浅仓，不带 depth 拉一个新提交会连带拉整个仓的
    历史（overview #236）。深度取 50 而不是 1：拉下来还要判它是不是 HEAD 的祖先，
    只拉 1 层时新提交的父提交在本地找不到，`merge-base` 走不到 HEAD。"""
    return git(repo, _gf.fetch_args(remote, [commit], shallow=_gf.is_shallow(repo, git),
                                    depth=depth, quiet=True))


def deepen_head(repo: Path, remote: str = "origin", git: GitRunner = default_git,
                deepen: int = 200) -> bool:
    """浅仓里把 HEAD 的历史往下加深 `deepen` 层（`fetch --deepen`，从现有浅边界往下接，
    不拉全量）。完整仓什么都不做、返回 False。

    为什么要：浅仓里比浅边界更老的提交本地没有，`merge-base --is-ancestor` 也走不过边界，
    `check_cv` 会把「包的 cv 是 HEAD 的老祖先」误判成找不到／不兼容（09-28 服务器 cv
    浅边界在 `b961082`，之前打的包都会撞上）。"""
    if not _gf.is_shallow(repo, git):
        return False
    head = rev_parse(repo, "HEAD", git)
    if head is None:
        return False
    return git(repo, ["fetch", "-q", f"--deepen={deepen}", remote, head]).returncode == 0


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
