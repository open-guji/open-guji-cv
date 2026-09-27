# -*- coding: utf-8 -*-
"""字形库 store ＋ 人裁事件/裁决定时导出：db → output/glyph_store/，
各书 feedback/ 与 config/crop_exclusions*.jsonl → 提交、推 guji-workspace。

    PYTHONPATH=. python scripts/glyph_store_sync.py [--root ~/guji-workspace] [--no-push]

正本见 overview 仓 进度/字形库/09-多机同步-字形库与模型.md §〇：人裁进库只写 db，store 要有人
记得导出才更新（09-25 实测四庫 820 条人裁只在 db 里、北行整本没导出过）。本脚本由 systemd
用户定时器 `guji-glyph-store-sync.timer` 每 30 分钟跑一次（云服务器是字形库唯一写者）。

每个带 `output/glyph.db` 的书目录：
1. 算 db 内容签名（刻例 / 字头 / 准入审计 / meta 的逐行哈希），与上次导出时记下的比，
   相同且 store 与 db 刻例数一致就跳过——每 30 分钟整库重写 1.7 万张 PNG 没必要；
2. 否则 `export_store` 全量导出（幂等：内容没变的文件字节不变，git 看不到差异）。

2026-09-26 起（overview 任务书-K-发布与部署.md §一·4）额外把每本书的
`feedback/`（事件、裁决、绑定表）与 `config/crop_exclusions*.jsonl`（排除名单）
一并纳入同一次 add/commit/push——这些之前只在服务器本地磁盘上，别的机器（云端
开发、用户本机）读不到最新的人裁状态。**这两类东西的写主体不同**：字形库
store 的写者是本脚本自己（`export_store`）；`feedback/`／排除名单是控制台
（人在点裁决）随时在写的，本脚本只是**照抄现状去提交**，不生成不修改内容。

**写锁**（2026-09-26，H 道「人裁单写者」合入后）：每本书各自的 `feedback/` 目录
一把 `open_guji_cv.feedback.lock.book_feedback_lock`——控制台裁决 `POST /api/events`
等写入口现在都走同一把锁，本脚本读 `feedback/` 去 `git add` 之前也要**先拿到那本书的锁**，
不然仍可能读到「正在写一半」的状态。按书各拿一把、不是整个 `main()` 一把大锁：
几十本书不该因为其中一本在写就全部等。`acquire_feedback_lock` 一次性拿齐本轮涉及
的每本书的锁（`ExitStack`），持锁期间做 `git add`/`diff`/`commit`——add 那一刻的内容
即是拿到锁那一刻的快照，之后再有新裁决进来是下一轮的事，不属于这次提交漏读。

用 flock 防重入；日志写 stdout（systemd 接到 runs/glyph_store_sync.log）。
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "glyph_store_sync"


def log(msg: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def db_signature(db: Path) -> str:
    """db 里会导出的那部分内容的哈希（字体域不导出，也不算）。"""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    h = hashlib.sha256()
    try:
        fe = {r[0] for r in c.execute("SELECT edition_tag FROM sources WHERE kind='font'")}
        for q in ("SELECT e.instance_id, g.edition_tag, g.char FROM exemplars e "
                  "JOIN glyphs g USING(glyph_id) ORDER BY e.instance_id",
                  "SELECT instance_id, label, semantic, unicode_cp, ids, updated_at, "
                  "length(patch_png) FROM instances ORDER BY instance_id",
                  "SELECT instance_id, char, provenance, admitted_at FROM admissions ORDER BY instance_id",
                  "SELECT edition_tag, char, semantic, unicode_cp, ids, status, n_confirmed FROM glyphs "
                  "ORDER BY edition_tag, char",
                  "SELECT * FROM sources ORDER BY source_id"):
            for row in c.execute(q):
                if any(isinstance(v, str) and v in fe for v in row[:2]):
                    continue
                h.update(repr(row).encode("utf-8"))
        try:
            for row in c.execute("SELECT key, value FROM meta ORDER BY key"):
                h.update(repr(row).encode("utf-8"))
        except sqlite3.OperationalError:
            pass                                    # 旧库没有 meta 表
    finally:
        c.close()
    return h.hexdigest()


def export_one(ws: Path) -> bool:
    """导出一本书。返回是否做了导出。"""
    os.environ["GUJI_WORKSPACE"] = str(ws)
    from open_guji_cv.clustering.glyph_db import GlyphDB, export_store
    from open_guji_cv.clustering.glyph_ledger import connect_ro, store_drift
    db = ws / "output" / "glyph.db"
    store = ws / "output" / "glyph_store"
    sig = db_signature(db)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_f = STATE_DIR / f"{ws.name}.json"
    last = json.loads(state_f.read_text(encoding="utf-8")) if state_f.exists() else {}
    c = connect_ro(db)
    try:
        drift = store_drift(c, store)
    finally:
        c.close()
    if last.get("sig") == sig and drift.get("ok"):
        log(f"{ws.name[:12]}: 无变化（刻例 {drift['db_exemplars']}）")
        return False
    g = GlyphDB(str(db))
    try:
        s = export_store(g, store)
    finally:
        g.close()
    (store / "_snapshot.json").write_text(json.dumps({"instances": s["instances"]}, ensure_ascii=False,
                                                     indent=1), encoding="utf-8")
    state_f.write_text(json.dumps({"sig": sig, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                   "exemplars": s["exemplars"]}), encoding="utf-8")
    log(f"{ws.name[:12]}: 已导出 刻例 {s['exemplars']}（此前 store {drift.get('store_exemplars')}）")
    return True


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=check)


#: 排除名单三个文件名固定在 workspace `config/` 下（见 `core/workspace.py`
#: `EXCLUSIONS_REL` 与它旁边的 `_retired`/`_released` 变体，实测各书工作区都有）。
_EXCLUSION_NAMES = ("crop_exclusions.jsonl", "crop_exclusions_retired.jsonl",
                    "crop_exclusions_released.jsonl")


def feedback_rel_paths(ws: Path) -> list[str]:
    """一本书里「人裁状态」相关的路径（相对这本书的目录）：事件、裁决、绑定表、
    排除名单。**只认路径存不存在，不看内容改没改**——changed 与否交给下面
    `git diff --cached --quiet` 判断，这里只负责「有就纳入这次 add」。"""
    rels = []
    if (ws / "feedback").is_dir():
        rels.append("feedback")
    for name in _EXCLUSION_NAMES:
        if (ws / "config" / name).exists():
            rels.append(f"config/{name}")
    return rels


def acquire_feedback_lock(books: list[Path]):
    """按书各拿一把 `feedback/` 写锁（`ExitStack`：一次性全拿齐，持锁期间做 add/commit）。

    只给**有 `feedback/` 目录**的书拿锁——纯字形库导出、没有人裁状态的书不需要。
    """
    from contextlib import ExitStack

    from open_guji_cv.feedback.lock import book_feedback_lock
    stack = ExitStack()
    for ws in books:
        if (ws / "feedback").is_dir():
            stack.enter_context(book_feedback_lock(ws / "feedback"))
    return stack


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path.home() / "guji-workspace"))
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()
    root = Path(a.root).expanduser()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock = open(STATE_DIR / "lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("上一轮还在跑，跳过")
        return 0
    books = sorted(d for d in root.iterdir() if (d / "output" / "glyph.db").exists())
    # 人裁状态按「有没有 feedback/排除名单」挑书，不按有没有自己的库（2026-09-27，K 快照自动导入）：
    # 借别家库的书（全唐文借四庫库）没有 output/glyph.db，原先整本被跳过，控制台上的裁决回不到 git。
    fb_books = sorted(d for d in root.iterdir() if d.is_dir() and feedback_rel_paths(d))
    changed = []
    for ws in books:
        try:
            if export_one(ws):
                changed.append(ws)
        except Exception as e:                      # noqa: BLE001 —— 一本书坏了不拖别的书
            log(f"{ws.name[:12]}: 导出失败 {type(e).__name__}: {e}")
    glyph_paths = [str((ws / "output" / "glyph_store").relative_to(root)) for ws in changed]
    # feedback/ 与排除名单**每本书都查**，不限于这次导出了字形库的那些——它们的
    # 写主体是控制台裁决，跟字形库 store 是否需要重新导出没有关系（09-26 加）。
    feedback_paths = [str((ws / rel).relative_to(root)) for ws in fb_books for rel in feedback_rel_paths(ws)]
    paths = glyph_paths + feedback_paths
    if not paths:
        return 0
    with acquire_feedback_lock(fb_books):
        git(root, "add", "--", *paths)
        if git(root, "diff", "--cached", "--quiet", "--", *paths, check=False).returncode == 0:
            log("导出/事件都与已提交的一致，不提交")
            return 0
        glyph_names = "、".join(ws.name.split("-", 1)[-1][:6] for ws in changed)
        msg_parts = []
        if glyph_names:
            msg_parts.append(f"字形库 store：{glyph_names}")
        if feedback_paths:
            msg_parts.append(f"人裁事件/裁决/绑定表/排除名单：{len(fb_books)} 本书检查、"
                             f"{sum(1 for p in feedback_paths if p)} 个路径纳入")
        msg = ("定时同步：" + "；".join(msg_parts) + "\n\n"
              "scripts/glyph_store_sync.py（systemd guji-glyph-store-sync.timer，每 30 分钟）。\n"
              "db 不进 git，真源是 output/glyph_store/；feedback/ 只照抄现状提交，"
              "本脚本不生成不修改内容。")
        git(root, "commit", "-q", "-m", msg, "--", *paths)
    if a.no_push:
        log("已提交（--no-push）")
        return 0
    for attempt in (1, 2):
        pr = git(root, "pull", "-q", "--rebase", "--autostash", check=False)
        ps = git(root, "push", "-q", check=False)
        if ps.returncode == 0:
            log(f"已提交并推送：{git(root, 'log', '--oneline', '-1').stdout.strip()}")
            return 0
        log(f"推送失败（第 {attempt} 次）：{(pr.stderr + ps.stderr).strip()[:300]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
