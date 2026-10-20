# -*- coding: utf-8 -*-
"""合 PR 之前核对目标分支对不对（GUJI-657；规矩见 `doc/版本号规矩.md` 第三节，10-20 起 dev 集成、发版切 rc）。

M8 教训：PR 合进已经发版（main 上打了 `vX.Y.Z`）的 rc 分支，改动不进任何后续版本，
#184/#192 靠 #206、#242/#253/#260/#263 靠 #265 才补回。

    python scripts/check_rc_target.py dev              # 0：日常 PR 都投 dev
    python scripts/check_rc_target.py rc/v0.4.9        # 0 = 还能收本版修复（记得合回 dev）；1 = 该版已发；2 = 不是最新一条 rc
    python scripts/check_rc_target.py main             # 4：只有发版 PR（rc 合进 main）才投 main

只读：用 `git ls-remote` 查远端的 tag 与 `rc/*` 分支，不改任何东西。`vX.Y.Z-rc.N` 不算发版。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

_RC = re.compile(r"^rc/v(\d+)\.(\d+)\.(\d+)$")


def _ver(branch: str) -> tuple[int, int, int] | None:
    m = _RC.match(branch)
    return tuple(int(x) for x in m.groups()) if m else None  # type: ignore[return-value]


def verdict(target: str, tags: set[str], rc_heads: list[str]) -> tuple[int, str]:
    """target 是 PR 的目标分支；tags 是远端 tag 名（不带 refs/tags/）；rc_heads 是远端 `rc/*` 分支名。"""
    if target == "dev":
        return 0, "dev 是日常集成分支，可以合（门槛：不破坏现有流程、全量测试过）"
    if target == "main":
        return 4, "main 只接发版：日常 PR 改投 dev；只有 rc 合进 main 的发版 PR 才投 main"
    v = _ver(target)
    if v is None:
        return 3, f"{target} 不是 dev，也不是 rc/vX.Y.Z"
    tag = "v%d.%d.%d" % v
    if tag in tags:
        newer = sorted((h for h in rc_heads if (_ver(h) or (0, 0, 0)) > v), key=_ver)
        return 1, f"{tag} 已发版，合进 {target} 的改动不会进任何版本，改投 dev"
    newest = max((h for h in rc_heads if _ver(h)), key=_ver, default=None)
    if newest and _ver(newest) > v:
        return 2, f"{target} 不是最新一条 rc（最新是 {newest}），确认是不是该改投"
    return 0, f"{target} 还没发版（远端没有 {tag}），可以合——rc 只收本版修复，同一修复记得合回 dev"


def _remote(ref_glob: str, kind: str) -> list[str]:
    out = subprocess.run(["git", "ls-remote", f"--{kind}", "origin", ref_glob],
                         check=True, capture_output=True, text=True).stdout
    pre = "refs/tags/" if kind == "tags" else "refs/heads/"
    return sorted({ln.split("\t", 1)[1][len(pre):].removesuffix("^{}") for ln in out.splitlines() if "\t" in ln})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", help="PR 的目标分支：dev、rc/vX.Y.Z 或 main")
    a = ap.parse_args(argv)
    code, msg = verdict(a.target, set(_remote("v*", "tags")), _remote("rc/*", "heads"))
    print(("✓ " if code == 0 else "✗ ") + msg)
    return code


if __name__ == "__main__":
    sys.exit(main())
