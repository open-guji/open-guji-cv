"""从 guji-workspace 的某个 git 提交里读文件（不看工作树）。

导入与核对都钉在一个提交上：工作树有没有改动、是不是稀疏检出都不影响结果。
只读 ``scope.classify`` 认为要进库的文件，别的 blob 不碰（部分克隆里它们可能不在本地）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .scope import classify


class BlobReader:
    """常驻一个 ``git cat-file --batch``，按 blob id 取内容。"""

    def __init__(self, repo: str | Path):
        self.proc = subprocess.Popen(
            ["git", "-C", str(repo), "cat-file", "--batch"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def read(self, oid: str) -> bytes:
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(oid.encode() + b"\n")
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().split()
        if len(header) < 3 or header[1] != b"blob":
            raise RuntimeError(f"读不到 blob {oid}: {header!r}")
        size = int(header[2])
        data = self.proc.stdout.read(size)
        self.proc.stdout.read(1)          # 结尾换行
        return data

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.wait()


def resolve(repo: str | Path, rev: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", f"{rev}^{{commit}}"], text=True).strip()


def list_tree(repo: str | Path, commit: str) -> list[tuple[str, str]]:
    """提交里的全部文件：(仓内路径, blob id)。"""
    out = subprocess.check_output(
        ["git", "-C", str(repo), "ls-tree", "-r", "-z", "--full-tree", commit])
    items = []
    for ent in out.split(b"\0"):
        if not ent:
            continue
        meta, path = ent.split(b"\t", 1)
        _mode, typ, oid = meta.split()
        if typ == b"blob":
            items.append((path.decode("utf-8"), oid.decode()))
    return items


def workspaces_in_tree(tree: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """按工作区目录分组：{目录名: [(工作区内相对路径, blob id)]}。

    工作区 = 仓根下一级、含 workspace.yaml 的目录。只留要进库的文件，
    以及不进库文件的路径（blob id 为空，只为报告「跳过了什么」）。
    """
    dirs = {p.split("/", 1)[0] for p, _ in tree if p.count("/") == 1
            and p.endswith("/workspace.yaml")}
    groups: dict[str, list[tuple[str, str]]] = {d: [] for d in sorted(dirs)}
    for path, oid in tree:
        top, _, rel = path.partition("/")
        if top not in groups or not rel:
            continue
        groups[top].append((rel, oid if classify(rel) is not None else ""))
    return groups
