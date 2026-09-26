# -*- coding: utf-8 -*-
"""字形库 store 定时导出：db → output/glyph_store/ → 提交、推 guji-workspace（2026-09-26）。

    PYTHONPATH=. python scripts/glyph_store_sync.py [--root ~/guji-workspace] [--no-push]

正本见 overview 仓 进度/字形库/09-多机同步-字形库与模型.md §〇：人裁进库只写 db，store 要有人
记得导出才更新（09-25 实测四庫 820 条人裁只在 db 里、北行整本没导出过）。本脚本由 systemd
用户定时器 `guji-glyph-store-sync.timer` 每 30 分钟跑一次（云服务器是字形库唯一写者）。

每个带 `output/glyph.db` 的书目录：
1. 算 db 内容签名（刻例 / 字头 / 准入审计 / meta 的逐行哈希），与上次导出时记下的比，
   相同且 store 与 db 刻例数一致就跳过——每 30 分钟整库重写 1.7 万张 PNG 没必要；
2. 否则 `export_store` 全量导出（幂等：内容没变的文件字节不变，git 看不到差异）；
3. 所有书导出完，只 `git add` 各书的 `output/glyph_store/`，按路径提交，`pull --rebase` 后推。
   工作区里别的会话没提交的改动一概不碰（pathspec 提交 + autostash）。

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
    changed = []
    for ws in books:
        try:
            if export_one(ws):
                changed.append(ws)
        except Exception as e:                      # noqa: BLE001 —— 一本书坏了不拖别的书
            log(f"{ws.name[:12]}: 导出失败 {type(e).__name__}: {e}")
    paths = [str((ws / "output" / "glyph_store").relative_to(root)) for ws in changed]
    if not paths:
        return 0
    git(root, "add", "--", *paths)
    if git(root, "diff", "--cached", "--quiet", "--", *paths, check=False).returncode == 0:
        log("导出了但内容与已提交的一致，不提交")
        return 0
    names = "、".join(ws.name.split("-", 1)[-1][:6] for ws in changed)
    msg = (f"字形库 store 定时导出：{names}\n\n"
           f"scripts/glyph_store_sync.py（systemd guji-glyph-store-sync.timer，每 30 分钟）。\n"
           f"db 不进 git，真源是 output/glyph_store/。")
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
