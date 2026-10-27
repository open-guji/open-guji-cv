# -*- coding: utf-8 -*-
"""装着的 cv 是哪个版本，以及「册配置固定的版本」护栏（GUJI-577／GUJI-601）。

口径见 `doc/版本号规矩.md` 第五节：

- `cv_version`：生成产物的代码对应的最近一个正式 tag，去掉 `v` 前缀，如 `"0.3.0"`；
  不在 tag 上（dev、rc、任意提交）时写下一个 PATCH 的 dev 号加提交 hash，如 `"0.3.1.dev2+g1a2b3c4d5e6f"`
  （PEP 440；2026-10-23 起，之前是 `0.3.0+2`）。rc tag 不算。浅克隆取不到 tag 时写 `"dev+g<sha12>"`。
- `cv_commit`：完整 commit sha。

册配置 `books/<册>.yaml` 写 `cv_version: "0.3.0"`（设计 §2a 第 1、6 条）时，`guji step`／
`pipeline` 发现装的版本不同就拒跑，免得有人在 main 上顺手一跑把整册弄过期。
在中心库实验分支（`GUJI_DATA_BRANCH=exp/*`，产物落该分支自己的目录）上跑只提醒（`isolated_branch`）。
本模块不在任何 Step 的 `code_deps` 里，改它不动 19 步 `code_hash`。"""

from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
_DESCRIBE_RE = re.compile(r"^v(\d+\.\d+\.\d+)-(\d+)-g([0-9a-f]+)$")


def _git(*args: str, repo: Path) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=5)
    except Exception:  # noqa: BLE001 —— 没装 git、不是检出：退回包元数据
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


SHA_LEN = 12
#: 正式版 cv_version：只有三段数字（不带 .devN、+g…、+dirty）
FORMAL_RE = re.compile(r"^\d+\.\d+\.\d+$")


def is_formal(v: str | None) -> bool:
    return bool(FORMAL_RE.match(v or ""))


def parse_describe(s: str) -> str | None:
    """`git describe --long` 的输出 → cv_version。`v0.3.0-0-g…` → `0.3.0`；
    不在 tag 上：`v0.3.0-2-g1a2b…` → `0.3.1.dev2+g1a2b3c4d5e6f`（下一个 PATCH 的第 2 个 dev 提交，带 12 位 hash）。"""
    m = _DESCRIBE_RE.match(s.strip())
    if not m:
        return None
    ver, n, sha = m.group(1), int(m.group(2)), m.group(3)
    if n == 0:
        return ver
    major, minor, patch = ver.split(".")
    return f"{major}.{minor}.{int(patch) + 1}.dev{n}+g{sha[:SHA_LEN]}"


def _with_dirty(ver: str) -> str:
    """有没提交的改动：PEP 440 本地段里加 `dirty`（`0.3.0+dirty`、`0.3.1.dev2+g….dirty`）。"""
    return f"{ver}.dirty" if "+" in ver else f"{ver}+dirty"


def _package_version() -> str | None:
    try:
        from importlib.metadata import version
        return version("open-guji-cv")
    except Exception:  # noqa: BLE001
        return None


@lru_cache(maxsize=4)
def describe(repo: Path | None = None) -> tuple[str | None, str | None]:
    """(cv_version, cv_commit)。是 cv 自己的 git 检出就按 tag 算；否则用安装包的版本号，commit 为 None。

    - `open_guji_cv/` 下有没提交的改动：版本加 `dirty`（如 `0.3.0+dirty`、`0.3.1.dev2+g….dirty`），
      固定了版本的册会因此拒跑——本地改过的代码跑出的产物不算这个版本。
    - 只认仓根就是 `repo` 的检出：包装在别的 git 仓里（如工作区仓下的 .venv）时
      不去读外层仓的 HEAD，退回包版本号。
    - 浅克隆或没拉 tag 时 describe 失败，版本记 `dev+g<sha12>`：知道是哪个提交、不知道离哪个 tag 多远，
      照样不算正式版（`mismatch` 的提示里会说原因）。"""
    root = (Path(repo) if repo else _REPO).resolve()
    top = _git("rev-parse", "--show-toplevel", repo=root)
    commit = _git("rev-parse", "HEAD", repo=root) if top and Path(top).resolve() == root else None
    if commit:
        d = _git("describe", "--tags", "--long", "--abbrev=40",
                 "--match", "v[0-9]*.[0-9]*.[0-9]*", "--exclude", "*-*", repo=root)
        ver = (parse_describe(d) if d else None) or f"dev+g{commit[:SHA_LEN]}"
        if _git("status", "--porcelain", "-uno", "--", "open_guji_cv", repo=root):
            ver = _with_dirty(ver)
        return ver, commit
    return _package_version(), None


#: 护栏放行时记下的理由（`--allow-cv-mismatch --why …` 或实验分支），经环境变量传给逐步子进程（子进程的护栏读它）
OVERRIDE_ENV = "GUJI_CV_OVERRIDE"
OVERRIDE_HINT = ("用当前代码做实验请在中心库实验分支上跑（`GUJI_DATA_BRANCH=exp/GUJI-<卡号>-<说明>`，"
                 "产物不碰正式目录）；确要在这里跑加 `--allow-cv-mismatch --why \"<理由>\"`")


def manifest_fields() -> dict[str, str | None]:
    """写进每条 `ManifestEntry` 的版本字段。`cv_override` 由护栏放行时补（`cli_v2._guard_cv_version`）。"""
    from .contract import CONTRACT_VERSION, manager_version
    ver, commit = describe()
    return {"cv_version": ver, "cv_commit": commit, "cv_override": None,
            "contract_version": CONTRACT_VERSION, "manager_version": manager_version()}


def isolated_branch() -> str | None:
    """当前在中心库实验分支上、产物落该分支自己的目录 → 分支名；否则 None。

    `GUJI_PRODUCTS_DIR` 显式指了目录、或工作区没迁中心库（产物不随分支换目录）时不算，照旧过护栏。"""
    import os
    from . import workspace as W
    if os.environ.get("GUJI_PRODUCTS_DIR") or W._branch_local(W.PRODUCTS_REL) is None:
        return None
    b = W.active_branch()
    return b if W.is_exp_branch(b) else None


def normalize(v: str | None) -> str | None:
    """册配置里写成 `v0.3.0` 也认。"""
    if v is None:
        return None
    v = str(v).strip()
    return v[1:] if v.startswith("v") else v


def mismatch(book_cv_version: str | None, installed: str | None = None) -> str | None:
    """册配置固定了版本、而装的不是它 → 一句说明；没固定或一致 → None。"""
    want = normalize(book_cv_version)
    if not want:
        return None
    if installed is not None:
        have, commit = installed, None
    else:
        have, commit = describe()
    if have == want:
        return None
    why = ""
    if have and have.startswith("dev+g"):
        why = "（git describe 找不到正式 tag：可能是浅克隆或没拉 tag，先 `git fetch --tags --unshallow`）"
    elif have and have.endswith("dirty"):
        why = "（open_guji_cv/ 下有没提交的改动）"
    return (f"册配置固定 cv_version={want}，装的是 {have or '未知版本'}{why}。"
            f"请检出 v{want} 再跑；{OVERRIDE_HINT}")


def frozen_mismatch(freeze: dict | None, installed_commit: str | None = None,
                    installed_version: str | None = None) -> str | None:
    """冻结册（yaml 有 `freeze:`）护栏（M10·D7，GUJI-694）：装的代码不是冻结时那份 → 一句说明；否则 None。

    冻结代码常在专门的分支上（vol01 是 v0.4.5＋人工指定格补丁，`describe` 得 `0.4.5+N`），
    所以写了 `freeze.cv_commit` 就按**提交**比，没写才按 `freeze.cv_version` 比版本。
    顶层 `cv_version` 的护栏（`mismatch`）照旧另查；冻结册顶层常常没写它，以前在 main 上照样能跑。"""
    fz = freeze or {}
    if not (fz.get("snapshot") or fz.get("manifest") or fz.get("pack")):
        return None
    where = fz.get("pack") or fz.get("snapshot") or fz.get("manifest")
    want_commit = str(fz.get("cv_commit") or "").strip()
    if installed_commit is None and installed_version is None:
        installed_version, installed_commit = describe()
    if want_commit:
        if installed_commit and installed_commit.startswith(want_commit[:12]) and (
                len(want_commit) < 40 or installed_commit == want_commit):
            if installed_version and installed_version.endswith("dirty"):
                return (f"本册已冻结（{where}），装的提交对，但 open_guji_cv/ 下有没提交的改动。"
                        f"1.0 后修订见 runbook「四·五」；{OVERRIDE_HINT}")
            return None
        return (f"本册已冻结（{where}，cv_commit={want_commit[:12]}），"
                f"装的是 {(installed_commit or '未知提交')[:12]}。请在冻结 tag 的检出上跑（如 `git worktree add … freeze/<…>`）；"
                f"1.0 后修订见 runbook「四·五」；{OVERRIDE_HINT}")
    want = normalize(fz.get("cv_version"))
    if want and normalize(installed_version) != want:
        return (f"本册已冻结（{where}，cv_version={want}），装的是 {installed_version or '未知版本'}。"
                f"请检出 v{want} 再跑；{OVERRIDE_HINT}")
    return None
