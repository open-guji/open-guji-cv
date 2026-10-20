# -*- coding: utf-8 -*-
"""合 PR 之前核对目标待发分支 `rc/vX.Y.Z` 还能不能收改动（GUJI-657）。

M8 教训：PR 合进已经发版（main 上打了 `vX.Y.Z`）的 rc 分支，改动不进任何后续版本，
#184/#192 靠 #206、#242/#253/#260/#263 靠 #265 才补回。规矩见 `doc/版本号规矩.md` 第三节。

    python scripts/check_rc_target.py rc/v0.4.8          # 0 = 可以合；1 = 该版已发；2 = 不是最新的待发分支

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
    """target 是 `rc/vX.Y.Z`；tags 是远端 tag 名（不带 refs/tags/）；rc_heads 是远端 `rc/*` 分支名。"""
    v = _ver(target)
    if v is None:
        return 3, f"{target} 不是 rc/vX.Y.Z 形式的待发分支"
    tag = "v%d.%d.%d" % v
    if tag in tags:
        newer = sorted((h for h in rc_heads if (_ver(h) or (0, 0, 0)) > v), key=_ver)
        hint = f"，改投 {newer[0]}" if newer else "，先开下一条待发分支再改投"
        return 1, f"{tag} 已发版，合进 {target} 的改动不会进任何版本{hint}"
    newest = max((h for h in rc_heads if _ver(h)), key=_ver, default=None)
    if newest and _ver(newest) > v:
        return 2, f"{target} 不是最新的待发分支（最新是 {newest}），确认是不是该改投"
    return 0, f"{target} 还没发版（远端没有 {tag}），可以合"


def _remote(ref_glob: str, kind: str) -> list[str]:
    out = subprocess.run(["git", "ls-remote", f"--{kind}", "origin", ref_glob],
                         check=True, capture_output=True, text=True).stdout
    pre = "refs/tags/" if kind == "tags" else "refs/heads/"
    return sorted({ln.split("\t", 1)[1][len(pre):].removesuffix("^{}") for ln in out.splitlines() if "\t" in ln})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", help="PR 的目标分支，如 rc/v0.4.8")
    a = ap.parse_args(argv)
    code, msg = verdict(a.target, set(_remote("v*", "tags")), _remote("rc/*", "heads"))
    print(("✓ " if code == 0 else "✗ ") + msg)
    return code


if __name__ == "__main__":
    sys.exit(main())
