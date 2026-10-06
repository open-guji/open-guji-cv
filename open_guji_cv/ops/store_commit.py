"""`guji store check|commit`：字形库与人裁落真源并提交（overview#413 R5；runbook S14）。

做的事与 runbook S14 的手工步骤一致，只是收成一条命令、加上防呆：
1. （可选）`git fetch`，工作区所在仓落后远端时停下，先 pull 再来；
2. 把 `output/glyph.db` 导出到 `output/glyph_store/`（`glyph-db export` 同一个函数）；
3. 看 `feedback/ config/ review/ output/glyph_store/` 的改动：**成片删除就拒绝**（改判会撤旧进新，
   少量替换正常；大量删除通常是导出了一个空库或错库，见 workspace_layout 的教训）；
4. `commit`：只 add 这四个目录，提交；`--push` 再 `pull --rebase` 后推送。

不碰 `products*/`、`cache/`、`data_full/`。`check` 只做 1–3，不提交。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

DIRS = ["feedback", "config", "review", "output/glyph_store"]


def _git(ws: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ws), *args], capture_output=True, text=True, check=check, timeout=600)


def export(ws: Path) -> dict:
    from ..clustering.glyph_db import GlyphDB, export_store
    from ..core.workspace import glyph_db_path, glyph_store_path
    db_path = glyph_db_path()
    if not Path(db_path).exists():
        raise SystemExit(f"没有字形库索引 {db_path}：先 `guji glyph-db rebuild -w {ws}`")
    db = GlyphDB(db_path)
    try:
        summary = export_store(db, glyph_store_path())
    finally:
        db.close()
    # 与 scripts/snapshot_glyph_store.py 同：只记实例数、不记时间戳，重导同一个库应当零改动
    import json
    (Path(glyph_store_path()) / "_snapshot.json").write_text(
        json.dumps({"instances": summary.get("instances", 0)}, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def changes(ws: Path) -> dict:
    """四个目录相对 HEAD 的改动（含未跟踪文件）。"""
    num = _git(ws, "diff", "--numstat", "HEAD", "--", *DIRS).stdout
    add = dele = 0
    deleted_files: list[str] = []
    per_file = []
    for line in num.splitlines():
        a, d, f = line.split("\t", 2)
        a = 0 if a == "-" else int(a)
        d = 0 if d == "-" else int(d)
        add += a
        dele += d
        per_file.append((f, a, d))
    st = _git(ws, "status", "--porcelain", "--", *DIRS).stdout.splitlines()
    untracked = [ln[3:] for ln in st if ln.startswith("??")]
    deleted_files = [ln[3:] for ln in st if ln[:2].strip() == "D"]
    return {"added_lines": add, "deleted_lines": dele, "untracked": len(untracked),
            "deleted_files": deleted_files, "top_deletions": sorted(per_file, key=lambda x: -x[2])[:10],
            "n_changed": len(st)}


def mass_deletion(ch: dict, max_deleted_files: int = 20, ratio: float = 0.5, floor: int = 200) -> str | None:
    """成片删除的判据：删掉的文件超过 `max_deleted_files` 个，或删行数超过 `floor` 且超过增行数的 `ratio` 倍。"""
    if len(ch["deleted_files"]) > max_deleted_files:
        return f"删掉 {len(ch['deleted_files'])} 个文件（>{max_deleted_files}）"
    if ch["deleted_lines"] > floor and ch["deleted_lines"] > ratio * max(ch["added_lines"], 1):
        return f"删 {ch['deleted_lines']} 行、增 {ch['added_lines']} 行（删得比增得多一半以上）"
    return None


def behind_remote(ws: Path) -> int | None:
    if _git(ws, "fetch", "-q", check=False).returncode != 0:
        return None
    r = _git(ws, "rev-list", "--count", "HEAD..@{u}", check=False)
    return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else None


def run(ws: Path, *, commit: bool, push: bool, allow_deletions: bool, no_export: bool,
        message: str | None, fetch: bool = True) -> dict:
    res: dict = {"workspace": str(ws)}
    if fetch:
        n = behind_remote(ws)
        res["behind_remote"] = n
        if n:
            res["blocked"] = f"工作区所在仓落后远端 {n} 个提交：先 `git -C {ws} pull --rebase` 再来（别人可能刚推了 store）"
            return res
    if not no_export:
        res["export"] = export(ws)
        if not res["export"].get("instances"):
            res["blocked"] = "导出了 0 个实例：库是空的或指错了库（workspace_layout §四 的老坑），什么都没提交"
            return res
    ch = changes(ws)
    res["changes"] = ch
    why = mass_deletion(ch)
    res["mass_deletion"] = why
    if why and not allow_deletions:
        res["blocked"] = f"疑似成片删除：{why}。先查清（常见：导出了空库或错库），确认无误再加 --allow-deletions"
        return res
    if not commit:
        return res
    if ch["n_changed"] == 0:
        res["committed"] = None
        return res
    _git(ws, "add", "--", *[d for d in DIRS if (ws / d).exists()])   # 不存在的目录 git add 会报 pathspec 错
    msg = message or f"字形库与人裁落真源（guji store commit）：+{ch['added_lines']} −{ch['deleted_lines']} 行"
    _git(ws, "commit", "-q", "-m", msg)
    res["committed"] = _git(ws, "rev-parse", "--short", "HEAD").stdout.strip()
    if push:
        _git(ws, "pull", "-q", "--rebase")
        _git(ws, "push", "-q")
        res["pushed"] = True
    return res
