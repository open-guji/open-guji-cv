# -*- coding: utf-8 -*-
"""`guji snap watch`：服务器 systemd 定时器（`guji-snap-watch.timer`，15 分钟）跑。

一轮：`ls-remote 'refs/heads/snap/*'` → 一次 fetch 全部（孤儿单提交，`--depth 1`）→
读各包 manifest、算出谁被谁作废（`supersedes`）→ 按生成时间从旧到新逐包走
`importer.import_pack` → 结果写本地状态文件，**有变化的**写一张导入记录推 overview
`进度/图片初步数字化/进度/inbox/导入/<UTC 时戳>-import.md`（照搬部署记录的写法）。

状态文件记每条分支最后一次处理的 (提交, 状态)：终态（导入成功、sha 对不上、manifest 坏、
被作废）同一提交不再碰；`importer.RETRYABLE` 里的（锁被占、cv 不兼容、找不到工作区…）
每轮再试，但**状态没变就不再写记录**——锁占三小时不会刷出十二张一样的单。
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path
from typing import Callable

from . import gitio
from .importer import (BAD_MANIFEST, IMPORTED, RETRYABLE, ImportResult, default_freshness, import_pack,
                       read_manifest)
from .manifest import ManifestError

DEFAULT_STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "guji_snap" / "state.json"
RECORD_DIR = "项目进展/图片初步数字化/进度/inbox/导入"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def watch(*, ws_repo: Path, ws_roots: list[Path], cv_repo: Path, state_path: Path = DEFAULT_STATE,
          overview: Path | None = None, remote: str = "origin", dry_run: bool = False, push: bool = True,
          git: gitio.GitRunner = gitio.default_git,
          freshness_fn: Callable = default_freshness, importer: Callable = import_pack,
          url_fetch: Callable | None = None) -> dict:
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lockf = open(state_path.with_name(state_path.name + ".lock"), "w")
    try:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "busy", "note": "上一轮还在跑"}
        return _watch_locked(ws_repo=ws_repo, ws_roots=ws_roots, cv_repo=cv_repo, state_path=state_path,
                             overview=overview, remote=remote, dry_run=dry_run, push=push, git=git,
                             freshness_fn=freshness_fn, importer=importer, url_fetch=url_fetch)
    finally:
        lockf.close()


def _watch_locked(*, ws_repo, ws_roots, cv_repo, state_path, overview, remote, dry_run, push, git,
                  freshness_fn, importer, url_fetch) -> dict:
    try:
        listing = gitio.ls_remote_snaps(ws_repo, remote, git)
    except gitio.GitError as e:
        return {"status": "ls_remote_failed", "error": str(e)}
    state = _load(state_path)
    todo = [b for b, sha in listing.items()
            if b not in state or state[b].get("commit") != sha or state[b].get("status") in RETRYABLE]
    if not todo:
        return {"status": "idle", "packs": len(listing)}
    try:
        gitio.fetch_branches(ws_repo, sorted(listing), remote, git)
    except gitio.GitError as e:
        return {"status": "fetch_failed", "error": str(e)}
    manifests: dict[str, dict] = {}
    bad: dict[str, str] = {}
    for b in listing:
        try:
            manifests[b] = read_manifest(ws_repo, gitio.remote_ref(b, remote), git)
        except ManifestError as e:
            bad[b] = str(e)
    superseded: dict[str, str] = {}
    for b, m in manifests.items():
        for old in m.get("supersedes", []):
            superseded.setdefault(old, b)
    todo.sort(key=lambda b: (manifests.get(b, {}).get("created", ""), b))
    kw = {"url_fetch": url_fetch} if url_fetch else {}
    changed: list[ImportResult] = []
    results = []
    for b in todo:
        if b in bad:
            r = ImportResult(BAD_MANIFEST, b, {"commit": listing[b], "error": bad[b]})
        else:
            r = importer(b, ws_repo=ws_repo, ws_roots=ws_roots, cv_repo=cv_repo, remote=remote,
                         dry_run=dry_run, superseded_by=superseded.get(b), fetch=False, git=git,
                         freshness_fn=freshness_fn, **kw)
        results.append(r.to_dict())
        prev = state.get(b, {})
        if prev.get("commit") != listing[b] or prev.get("status") != r.status:
            changed.append(r)
        if not dry_run:
            state[b] = {"commit": listing[b], "status": r.status,
                        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "pack": r.detail.get("pack")}
    if not dry_run:
        _save(state_path, state)
    record = None
    if changed and overview and not dry_run:
        record = write_import_record(Path(overview), changed, push=push)
    return {"status": "ran", "packs": len(listing), "tried": len(todo),
            "imported": sum(1 for r in results if r["status"] == IMPORTED),
            "results": results, "record": str(record) if record else None}


# ── 导入记录 ─────────────────────────────────────────────────────────
_COLS = (("fresh", "新鲜"), ("stale", "过期"), ("missing", "缺失"), ("failed", "失败"), ("blocked", "阻塞"))


def _counts(d: dict | None) -> str:
    if not d:
        return "—"
    return " ".join(f"{zh}{d.get(k, 0)}" for k, zh in _COLS if d.get(k))


def format_freshness(before: dict | None, after: dict | None) -> list[str]:
    """`guji status` 的尾巴：每步导入前后的 新鲜/过期/缺失/失败/阻塞。"""
    before, after = before or {}, after or {}
    lines = []
    for label, d in (("导入前", before), ("导入后", after)):
        if "error" in d:
            lines.append(f"- {label}新鲜度量不出：`{d['error']}`")
    steps = [s for s in list(before) + [s for s in after if s not in before] if s != "error"]
    if not steps:
        return lines
    lines += ["", "| 步 | 导入前 | 导入后 |", "|---|---|---|"]
    for s in steps:
        lines.append(f"| {s} | {_counts(before.get(s))} | {_counts(after.get(s))} |")
    return lines


def render_record(results: list[ImportResult], ts: str) -> str:
    lines = [f"# 快照导入记录 {ts}（UTC）", "",
             "`guji snap watch`（服务器 `guji-snap-watch.timer`）自动写；只列状态有变化的包。", ""]
    for r in results:
        d = r.detail
        lines.append(f"## `{r.branch}` — `{r.status}`")
        lines.append("")
        if d.get("book"):
            lines.append(f"- 书：{d['book']}（工作区 {d.get('workspace', '?')}）；模式 `{d.get('mode')}`；"
                         f"{d.get('pages')} 页（{d.get('page_scope')}）；步 {', '.join(d.get('steps', []))}")
        if d.get("commit"):
            lines.append(f"- 包提交 `{d['commit'][:12]}`；包的 cv `{str(d.get('pack_cv', ''))[:12]}`")
        cvd = d.get("cv_check") or {}
        if cvd:
            lines.append(f"- 服务器 cv HEAD `{str(cvd.get('server_head', ''))[:12]}`；兼容判定："
                         + "；".join(f"`{k[:12]}` {v}" for k, v in cvd.get("checked", {}).items()))
        for k, zh in (("superseded_by", "被作废，取代它的是"), ("holder", "跑批锁持有者"),
                      ("downgraded", "会让这些步变旧，已整包换回（要换就 import --force）"),
                      ("workspace_created", "新建了工作区目录"),
                      ("error", "错误"), ("backup", "旧产物备份到"), ("attachments_placed", "附件落位"),
                      ("pruned_backups", "清掉的旧备份")):
            if d.get(k):
                lines.append(f"- {zh}：{d[k]}")
        if d.get("problems"):
            lines.append(f"- 校验问题 {d.get('n_problems')} 条（前 20）：")
            lines += [f"  - {p}" for p in d["problems"]]
        if "freshness_before" in d or "freshness_after" in d or "freshness_after_rolled_back" in d:
            lines += format_freshness(d.get("freshness_before"),
                                      d.get("freshness_after") or d.get("freshness_after_rolled_back"))
        if r.status == IMPORTED and d.get("mode") == "display-only":
            lines.append("")
            lines.append("> display-only：这些步只看不算，部署器的过期步队列会跳过它们，"
                         "过期是预期（指纹含服务器库/参数，与云端不同）。")
        lines.append("")
    return "\n".join(lines)


def write_import_record(overview: Path, results: list[ImportResult], *, push: bool = True,
                        git: gitio.GitRunner = gitio.default_git) -> Path:
    ts = time.strftime("%Y%m%d-%H%M", time.gmtime())
    out_dir = overview / RECORD_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{ts}-import.md"
    n = 2
    while path.exists():
        path = out_dir / f"{ts}-import-{n}.md"
        n += 1
    path.write_text(render_record(results, ts) + "\n", encoding="utf-8")
    # 总是提交（记录落进 overview 的历史）；`push=False` 只是不推（演练 / 假 origin）。
    rel = str(path.relative_to(overview))
    git(overview, ["add", "--", rel])
    commit = git(overview, ["commit", "-q", "-m", f"快照导入记录 {ts}", "--", rel])
    if push and commit.returncode == 0:
        for _ in range(2):
            git(overview, ["pull", "-q", "--rebase", "--autostash"])
            if git(overview, ["push", "-q"]).returncode == 0:
                break
    return path


def list_packs(ws_repo: Path, state_path: Path = DEFAULT_STATE, remote: str = "origin",
               git: gitio.GitRunner = gitio.default_git) -> list[dict]:
    listing = gitio.ls_remote_snaps(ws_repo, remote, git)
    state = _load(Path(state_path))
    return [{"branch": b, "commit": sha, "status": state.get(b, {}).get("status", "new"),
             "at": state.get(b, {}).get("at")} for b, sha in sorted(listing.items())]

