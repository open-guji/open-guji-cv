# -*- coding: utf-8 -*-
"""发版之后核对：每个发进 main 的版本都有 tag，且 tag 打在 main 的发版合并提交上（规矩见 `doc/版本号规矩.md` 第三节第 5、9 条）。

用户 2026-10-20 定：rc 发进 main 之后，main 上必须有对应的 `vX.Y.Z`，以后按版本号就能找到它在 main 的哪个提交。

    python scripts/check_release_tags.py               # 0 = 全部对得上；1 = 有已发版却缺 tag、或 tag 不在 main 主线上
    python scripts/check_release_tags.py --list        # 另列出每个版本对应的 main 提交

「已发版」的认法：main 主线（first-parent）上有提交的标题提到 `rc/vX.Y.Z`（发版 PR 的标题都这样写）。
还没发进 main 的 rc（测试中）不算缺。`vX.Y.Z-rc.N` 不检查。

会 `git fetch` 远端 main 与 tag（只更新远端跟踪引用和 tag，不动工作区），其余只读。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

_REL = re.compile(r"rc/v(\d+\.\d+\.\d+)\b")
_TAG = re.compile(r"^v\d+\.\d+\.\d+$")


def verdict(main_fp: list[tuple[str, str]], tags: dict[str, str],
            rc_heads: list[str]) -> tuple[int, list[str]]:
    """main_fp：main 主线提交 (sha, 标题)，新的在前；tags：tag 名 → 指向的提交 sha；rc_heads：远端 `rc/*` 分支名。

    返回 (退出码, 每个版本一行的说明)。
    """
    fp_shas = {sha for sha, _ in main_fp}
    released: dict[str, str] = {}                    # 版本 → main 上第一次提到它的发版提交
    for sha, subject in reversed(main_fp):
        for v in _REL.findall(subject):
            released.setdefault(v, sha)
    versions = set(released)
    versions |= {h[len("rc/v"):] for h in rc_heads if _REL.fullmatch(h)}
    versions |= {t[1:] for t in tags if _TAG.match(t) and tags[t] in fp_shas}

    bad = False
    lines: list[str] = []
    for v in sorted(versions, key=lambda s: tuple(int(x) for x in s.split("."))):
        tag, rel = "v" + v, released.get(v)
        got = tags.get(tag)
        if got is None:
            if rel:
                bad = True
                lines.append(f"✗ {tag} 已发进 main（{rel[:8]}）但没有 tag：在这个合并提交上补打")
            else:
                lines.append(f"· {tag} 还没发进 main（rc/{tag} 测试中），不用 tag")
        elif got not in fp_shas:
            bad = True
            lines.append(f"✗ {tag} 指向 {got[:8]}，不在 main 主线上" + (f"（发版提交是 {rel[:8]}）" if rel else ""))
        elif rel and got != rel:
            lines.append(f"✓ {tag} → main {got[:8]}（提到 rc/{tag} 的提交是 {rel[:8]}，核一下）")
        else:
            lines.append(f"✓ {tag} → main {got[:8]}")
    return (1 if bad else 0), lines


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true", help="每个版本都列出来（缺省只列有问题的）")
    a = ap.parse_args(argv)
    _git("fetch", "--quiet", "--tags", "origin", "+refs/heads/main:refs/remotes/origin/main")
    main_fp = [tuple(ln.split("\t", 1)) for ln in
               _git("log", "--first-parent", "--format=%H\t%s", "origin/main").splitlines() if "\t" in ln]
    tags = {}
    for ln in _git("for-each-ref", "--format=%(refname:short)\t%(*objectname)\t%(objectname)", "refs/tags/v*").splitlines():
        name, peeled, obj = ln.split("\t")
        tags[name] = peeled or obj                   # annotated tag 取它指向的提交
    heads = [ln.split("\t", 1)[1][len("refs/heads/"):] for ln in
             _git("ls-remote", "--heads", "origin", "rc/*").splitlines() if "\t" in ln]
    code, lines = verdict(main_fp, tags, heads)       # type: ignore[arg-type]
    for ln in lines:
        if a.list or not ln.startswith("✓"):
            print(ln)
    print("✓ 每个发进 main 的版本都有 tag" if code == 0 else "✗ 有版本缺 tag 或 tag 打错了地方，见上")
    return code


if __name__ == "__main__":
    sys.exit(main())
