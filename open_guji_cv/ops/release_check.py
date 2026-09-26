# -*- coding: utf-8 -*-
"""`guji release check <candidate-commit>`：候选提交跟上一个 `cv-*` tag 比。

**不跑管线**——只静态比较两个提交之间，参与某个 Step 指纹的文件（自己的模块 /
`code_deps` 模块 / `core/spec.py`）有没有变，据此报「这些 Step 会在所有用到它的
书上过期」（真的 stale/fresh 要跑 `guji status`，那是部署后 `deploy_check` 的事，
这里只读代码）。

全量测试「失败＋skip 的测试 ID 集合」与上一版（`ops/baseline_tests.json`）的差，
是发布前**唯一的硬门槛**（overview 总览/16 §3.2）：多了新失败/新跳过就不该发。

见 overview `进度/图片初步数字化/进度/总览/任务书-K-发布与部署.md` §一·1。
"""
from __future__ import annotations

import dataclasses
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

TAG_PREFIX = "cv-"
BASELINE_REL = "ops/baseline_tests.json"


# ── git 原语 ─────────────────────────────────────────────────────────
def run_git(repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check)


def last_release_tag(repo: Path, ref: str = "HEAD") -> str | None:
    """离 `ref`（默认 HEAD）**拓扑上最近**的 `cv-*` tag；没有就 `None`（还没发布过第一版）。

    按 `<tag>..ref` 的提交数排序取最小的那个，不按 `--sort=-creatordate`——轻量 tag
    的 creatordate 是它指向的提交的 committer date，两个提交在同一秒内造出来时
    （测试里几乎必然）排序不稳定；拓扑距离与时钟分辨率无关，对真实仓库也是更对的
    定义（「上一版」= HEAD 往回数最近碰到的那个发布 tag）。"""
    out = run_git(repo, "tag", "--list", f"{TAG_PREFIX}*")
    tags = [t.strip() for t in out.stdout.splitlines() if t.strip()]
    if not tags:
        return None

    def _distance(tag: str) -> int:
        r = run_git(repo, "rev-list", "--count", f"{tag}..{ref}")
        try:
            return int(r.stdout.strip())
        except ValueError:
            return 1 << 30    # 算不出来（tag 不是 ref 的祖先等）排最后

    return min(tags, key=_distance)


def changed_files(repo: Path, old_rev: str, new_rev: str) -> list[str]:
    """`old_rev` 为 `None`（没有上一个 tag）时，视为「全部都是新的」，调用方自己处理。"""
    out = run_git(repo, "diff", "--name-only", f"{old_rev}..{new_rev}")
    return [l for l in out.stdout.splitlines() if l.strip()]


def commit_titles(repo: Path, old_rev: str, new_rev: str) -> list[str]:
    """**按发生顺序**（`--reverse`，最早的在前）——`git log` 默认最新在前，
    但「改动摘要」要读的是「先做了什么、后做了什么」。"""
    out = run_git(repo, "log", "--reverse", "--pretty=format:%s", f"{old_rev}..{new_rev}")
    return [l for l in out.stdout.splitlines() if l.strip()]


def resolve_rev(repo: Path, rev: str) -> str | None:
    out = run_git(repo, "rev-parse", "--short", rev)
    return out.stdout.strip() or None


def next_version(repo: Path, today: str | None = None) -> str:
    """`cv-YYYY.MM.DD`；同一天已经打过就加 `-2`/`-3`……"""
    today = today or time.strftime("%Y.%m.%d")
    base = f"{TAG_PREFIX}{today}"
    out = run_git(repo, "tag", "--list", f"{base}*")
    existing = [l.strip() for l in out.stdout.splitlines() if l.strip()]
    if not existing:
        return base
    return f"{base}-{len(existing) + 1}"


# ── Step 指纹相关文件（静态，不跑管线）───────────────────────────────
def step_file_map() -> dict[str, set[str]]:
    """当前（已 import 的）`STEPS` 注册表：每个 step id → 参与它指纹的文件集合
    （自己的模块 + `code_deps` 模块 + `core/spec.py`），路径相对仓根。

    读的是**当前 checkout**——调用方（CLI）负责先把仓库切到要看的那个提交
    （通常候选提交就是当前 HEAD，不需要额外切换）。这层只管「文件 → step」的
    映射，`affected_steps` 再拿它去跟 `changed_files` 求交集，两者故意分开，
    后者不需要真的 import 这个包就能单测（见 `tests/test_ops_release_check.py`）。
    """
    import importlib.util

    from ..core.step import STEPS
    from ..core.workspace import REPO_ROOT

    def _file_of(mod_name: str) -> str | None:
        try:
            spec = importlib.util.find_spec(mod_name)
        except (ImportError, ValueError):
            return None
        if spec is None or spec.origin is None:
            return None
        try:
            return str(Path(spec.origin).resolve().relative_to(REPO_ROOT))
        except ValueError:
            return None

    spec_file = _file_of("open_guji_cv.core.spec")
    out: dict[str, set[str]] = {}
    for sid, step in STEPS.items():
        mods = [type(step).__module__, *step.spec.code_deps]
        files = {f for f in (_file_of(m) for m in mods) if f}
        if spec_file:
            files.add(spec_file)
        out[sid] = files
    return out


def affected_steps(step_files: dict[str, set[str]], changed: set[str]) -> dict[str, list[str]]:
    """哪些 step 的指纹相关文件出现在 `changed` 里，返回 `{step_id: [命中的文件…]}`
    （按文件名排序，空字典＝本轮改动不影响任何 Step 的指纹）。"""
    out: dict[str, list[str]] = {}
    for sid, files in step_files.items():
        hit = sorted(files & changed)
        if hit:
            out[sid] = hit
    return out


# ── 全量测试 ─────────────────────────────────────────────────────────
def run_test_suite(repo: Path, *, extra_args: list[str] | None = None,
                   python: str | None = None, tests_dir: str = "tests/") -> dict:
    """`pytest tests/ -s -p no:cacheprovider`（子会话须知 §五：不带 `-s` 会崩）。

    失败/跳过的测试 ID 从 `--junit-xml` 报告解析，**不摘 stdout 的 `-rfs` 摘要行**：
    `SKIPPED` 那行格式是 `SKIPPED [1] <file>:<line>: <理由>`，没有测试名，摘不出
    可比较的 ID（`FAILED` 那行倒是有 `<nodeid> - <理由>`，两种格式不一致）。
    junit `<testcase classname=… name=…>` 两个都有，且是内置功能，不必装插件。
    这里的「ID」是 `classname::name`，未必逐字节等于 pytest 原生 nodeid，但同一份
    代码两次跑出来的这个值稳定——`diff_test_sets` 只关心「两次跑之间变没变」，
    不关心跟 pytest `-v` 打印的字符串是否一模一样。"""
    py = python or sys.executable
    with tempfile.TemporaryDirectory() as td:
        report = Path(td) / "junit.xml"
        cmd = [py, "-m", "pytest", tests_dir, "-s", "-p", "no:cacheprovider", "-q", "--tb=no",
              f"--junit-xml={report}", *(extra_args or [])]
        proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
        failed, skipped = [], []
        if report.exists():
            for tc in ET.parse(report).getroot().iter("testcase"):
                tid = f"{tc.get('classname')}::{tc.get('name')}"
                if tc.find("failure") is not None or tc.find("error") is not None:
                    failed.append(tid)
                elif tc.find("skipped") is not None:
                    skipped.append(tid)
    return {"failed": sorted(failed), "skipped": sorted(skipped), "returncode": proc.returncode,
           "stdout_tail": "\n".join(proc.stdout.splitlines()[-40:])}


def diff_test_sets(baseline: dict | None, current: dict) -> dict:
    """`baseline` 为 `None`（第一次发布，没有 `ops/baseline_tests.json`）时，
    当前的失败/跳过全部记为「新增」——但 `regressed` 仍然只由 `new_*` 决定，
    调用方（`cmd_release_check`）自己决定首发要不要拿这个当门槛。"""
    base_failed = set((baseline or {}).get("failed", []))
    base_skipped = set((baseline or {}).get("skipped", []))
    cur_failed = set(current.get("failed", []))
    cur_skipped = set(current.get("skipped", []))
    new_failed = sorted(cur_failed - base_failed)
    new_skipped = sorted(cur_skipped - base_skipped)
    return {
        "new_failed": new_failed,
        "resolved_failed": sorted(base_failed - cur_failed),
        "new_skipped": new_skipped,
        "resolved_skipped": sorted(base_skipped - cur_skipped),
        "regressed": bool(new_failed or new_skipped),
    }


# ── RELEASES.md 草稿 ─────────────────────────────────────────────────
def render_release_draft(*, version: str, old_tag: str | None, new_rev: str,
                         titles: list[str], impact: dict[str, list[str]],
                         test_diff: dict, rollback_target: str | None) -> str:
    lines = [f"## {version}", "",
            f"- 提交：`{new_rev}`（对比 `{old_tag or '（无上一版，首次发布）'}`）",
            "", "### 改动摘要", ""]
    lines += [f"- {t}" for t in titles] if titles else ["- （两版之间没有新提交）"]
    lines += ["", "### 影响清单（指纹变了的步，读代码比对，未跑管线，只作报告不作硬门槛）", ""]
    if impact:
        lines += [f"- `{sid}`：{', '.join(files)}" for sid, files in sorted(impact.items())]
    else:
        lines.append("- 无（本轮改动不影响任何 Step 的指纹）")
    lines += ["", "### 全量测试（唯一硬门槛：不许比上一版多失败/多跳过）", "",
             f"- 新增失败：{', '.join(test_diff['new_failed']) or '无'}",
             f"- 新增跳过：{', '.join(test_diff['new_skipped']) or '无'}",
             f"- 本轮修复：{', '.join(test_diff['resolved_failed']) or '无'}"]
    lines += ["", "### 回滚目标", "", f"- `{rollback_target or old_tag or '（无）'}`", ""]
    return "\n".join(lines)


@dataclasses.dataclass
class ReleaseCheckResult:
    version: str
    old_tag: str | None
    candidate: str
    impact: dict[str, list[str]]
    test_result: dict
    test_diff: dict
    draft: str

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def release_check(repo: Path, candidate: str = "HEAD", *, against: str | None = None,
                  version: str | None = None, run_tests: bool = True) -> ReleaseCheckResult:
    """给 CLI 用的一站式入口；单测更愿意分别调上面的小函数（更好断言、不用真跑 pytest）。"""
    old_tag = against if against is not None else last_release_tag(repo)
    changed = set(changed_files(repo, old_tag, candidate)) if old_tag else set()
    impact = affected_steps(step_file_map(), changed)
    titles = commit_titles(repo, old_tag, candidate) if old_tag else []
    baseline_path = repo / BASELINE_REL
    baseline = None
    if baseline_path.exists():
        import json
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    current = run_test_suite(repo) if run_tests else {"failed": [], "skipped": [], "returncode": 0,
                                                       "stdout_tail": "（--no-tests，未跑）"}
    test_diff = diff_test_sets(baseline, current)
    ver = version or next_version(repo)
    draft = render_release_draft(version=ver, old_tag=old_tag, new_rev=resolve_rev(repo, candidate) or candidate,
                                 titles=titles, impact=impact, test_diff=test_diff, rollback_target=old_tag)
    return ReleaseCheckResult(version=ver, old_tag=old_tag, candidate=candidate, impact=impact,
                              test_result=current, test_diff=test_diff, draft=draft)
