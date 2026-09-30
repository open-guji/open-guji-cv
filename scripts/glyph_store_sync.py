# -*- coding: utf-8 -*-
"""字形库 store ＋ 人裁事件/裁决定时导出：db → output/glyph_store/，
各书 feedback/ 与 config/crop_exclusions*.jsonl → 提交、推 guji-workspace。

    PYTHONPATH=. python scripts/glyph_store_sync.py [--root ~/guji-workspace] [--no-push]

正本见 overview 仓 进度/字形库/09-多机同步-字形库与模型.md §〇：人裁进库只写 db，store 要有人
记得导出才更新（09-25 实测四庫 820 条人裁只在 db 里、北行整本没导出过）。本脚本由 systemd
用户定时器 `guji-glyph-store-sync.timer` 每 30 分钟跑一次（云服务器是字形库唯一写者）。

每个带 `output/glyph.db` 的书目录（2026-09-28 overview#234 改：原来「先导出覆盖 store、提交，再 pull」，
服务器旧库一导出就把 main 上别人进的 14 例「聞」冲掉了）：
1. **先 pull**；上游改过这本书的 store，就按「上次对齐的 store 树 → HEAD」这段差**增量套进 db**
   （三方合并，`clustering/store_merge.py`）——别人进的刻例进 db、别人撤的从 db 撤；
2. 算 db 内容签名，与上次导出时记下的比，签名相同、store 没被上游动过、刻例数一致就跳过；
3. **删除护栏**：导出会从 store 删掉的实例，每一例都要在 db 的撤例审计（`evictions` 表，
   `evict_instance` 写）或体检撤库裁决里有据，否则整本不导出、记日志（宁可不同步，也不删数据）；
4. 否则全量 `export_store`（幂等：内容没变的文件字节不变，git 看不到差异）。
推送成功后把这次的 store 树记进状态文件，当下一轮三方合并的 base。

2026-09-26 起（overview 任务书-K-发布与部署.md §一·4）额外把每本书的
`feedback/`（事件、裁决、绑定表）与 `config/crop_exclusions*.jsonl`（排除名单）
一并在同一轮里 add/commit/push（先于字形库单独提交，见 main）——这些之前只在服务器本地磁盘上，别的机器（云端
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
        # 近似字侧表（overview#276）：只标了/撤了近似、别的没动时也要导出。空表不进哈希，签名与加表前相同
        for q in ("SELECT instance_id, label, ids, note, created_at FROM approx_labels ORDER BY instance_id",
                  "SELECT instance_id, at FROM approx_clears ORDER BY instance_id, at"):
            try:
                for row in c.execute(q):
                    h.update(repr(row).encode("utf-8"))
            except sqlite3.OperationalError:
                pass                                # 旧库没有这两张表
    finally:
        c.close()
    return h.hexdigest()


def load_state(ws: Path) -> dict:
    f = STATE_DIR / f"{ws.name}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def save_state(ws: Path, **kw) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    st = {**load_state(ws), **kw}
    (STATE_DIR / f"{ws.name}.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


def store_rel(root: Path, ws: Path) -> str:
    return (ws / "output" / "glyph_store").relative_to(root).as_posix()


def merge_base(root: Path, ws: Path) -> str | None:
    """上一次 db 与 store 对齐时的 store 树（三方合并的公共祖先）。

    推送成功后记在状态文件里；没记过（第一次跑新逻辑）或那棵树已不在仓里，就取最近一条
    「定时同步」提交里的树——那就是服务器 db 上一次导出的内容，db 只会比它多、不会少。
    """
    from open_guji_cv.clustering.store_merge import last_sync_tree, tree_exists
    t = load_state(ws).get("store_tree")
    if tree_exists(root, t):
        return t
    return last_sync_tree(root, store_rel(root, ws))


def export_one(ws: Path, root: Path | None = None) -> dict:
    """合并上游 → 过删除护栏 → 导出一本书。返回 {"exported": bool, "blocked": bool, ...}。

    1. 上游（pull 进来的提交）改过这本书的 store：按 base→HEAD 的差增量套进 db（`merge_upstream`，
       规则见 `clustering/store_merge.py` 模块头）；
    2. db 签名没变、store 没被上游动过、刻例数对得上 → 跳过；
    3. 导出前算「会从 store 删掉哪些实例」，有删不出依据的（db 没有撤例审计）→ **整本不导出**，
       记日志，store 原样不动（宁可不同步，也不删数据）；
    4. 否则全量 `export_store`（幂等）。
    """
    os.environ["GUJI_WORKSPACE"] = str(ws)
    from open_guji_cv.clustering.glyph_db import GlyphDB, export_store
    from open_guji_cv.clustering.glyph_ledger import connect_ro, store_drift
    from open_guji_cv.clustering.store_merge import (merge_upstream, tree_sha,
                                                     unexplained_approx_deletions,
                                                     unexplained_deletions)
    root = root or ws.parent
    db = ws / "output" / "glyph.db"
    store = ws / "output" / "glyph_store"
    rel = store_rel(root, ws)
    out: dict = {"exported": False, "blocked": False, "merge": None}
    head_tree = tree_sha(root, "HEAD", rel)
    base = merge_base(root, ws)
    if base and head_tree and base != head_tree:
        g = GlyphDB(str(db))
        try:
            rep = merge_upstream(g, root, base, head_tree)
        finally:
            g.close()
        out["merge"] = rep.summary()
        log(f"{ws.name[:12]}: 上游改过 store，已套进 db：{json.dumps(rep.summary(), ensure_ascii=False)}")
    sig = db_signature(db)
    last = load_state(ws)
    c = connect_ro(db)
    try:
        drift = store_drift(c, store)
        guard = unexplained_deletions(db, c, store)
        guard_apx = unexplained_approx_deletions(c, store)
    finally:
        c.close()
    if guard["unexplained"]:
        out["blocked"] = True
        out["unexplained"] = guard["unexplained"]
        log(f"{ws.name[:12]}: 删除护栏拦下，本轮不导出——要从 store 删 {guard['planned']} 例，"
            f"其中 {len(guard['unexplained'])} 例 db 里没有撤例审计："
            f"{', '.join(guard['unexplained'][:20])}{' …' if len(guard['unexplained']) > 20 else ''}")
        return out
    if guard_apx["unexplained"]:
        # 近似字标记同理（overview#276）：实例还在、近似标记却要从 store 消失，db 又没有撤销审计
        out["blocked"] = True
        out["approx_unexplained"] = guard_apx["unexplained"]
        log(f"{ws.name[:12]}: 删除护栏拦下，本轮不导出——要从 store 撤 {guard_apx['planned']} 条近似字标记，"
            f"其中 {len(guard_apx['unexplained'])} 条 db 里没有撤销审计："
            f"{', '.join(guard_apx['unexplained'][:20])}")
        return out
    if last.get("sig") == sig and drift.get("ok") and head_tree == last.get("store_tree"):
        log(f"{ws.name[:12]}: 无变化（刻例 {drift['db_exemplars']}）")
        return out
    g = GlyphDB(str(db))
    try:
        s = export_store(g, store)
    finally:
        g.close()
    (store / "_snapshot.json").write_text(json.dumps({"instances": s["instances"]}, ensure_ascii=False,
                                                     indent=1), encoding="utf-8")
    save_state(ws, sig=sig, at=time.strftime("%Y-%m-%dT%H:%M:%S"), exemplars=s["exemplars"])
    out["exported"] = True
    log(f"{ws.name[:12]}: 已导出 刻例 {s['exemplars']}（此前 store {drift.get('store_exemplars')}；"
        f"删 {guard['planned']} 例，均有撤例审计）")
    return out


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


def has_upstream(root: Path) -> bool:
    return git(root, "rev-parse", "--abbrev-ref", "@{u}", check=False).returncode == 0


def restore_store(root: Path, rels: list[str]) -> None:
    """store 目录里没提交的改动丢掉：那是上一轮导出了没提交成的，db 还在，这轮重导即可。
    不丢的话 `pull --autostash` 会把它当成本地改动带着 rebase，与上游一冲突就卡住。"""
    for rel in rels:
        if git(root, "status", "--porcelain", "--", rel, check=False).stdout.strip():
            log(f"{rel}: 工作区有未提交的导出，丢弃后重导")
            git(root, "checkout", "-q", "HEAD", "--", rel, check=False)
            git(root, "clean", "-fdq", "--", rel, check=False)


def pull_upstream(root: Path, store_rels: list[str]) -> bool:
    """拉上游。冲突时先放弃 rebase；本地有没推上去的提交就退回上游、改动留在工作区下轮重交。"""
    pr = git(root, "pull", "-q", "--rebase", "--autostash", check=False)
    if pr.returncode == 0:
        return True
    git(root, "rebase", "--abort", check=False)
    ahead = git(root, "rev-list", "--count", "@{u}..HEAD", check=False).stdout.strip()
    log(f"pull 失败：{pr.stderr.strip()[:300]}")
    if ahead and ahead != "0":
        log(f"本地 {ahead} 个未推提交与上游冲突：退回上游，改动留在工作区（store 丢弃重导）")
        git(root, "reset", "-q", "--mixed", "@{u}", check=False)
        restore_store(root, store_rels)
        return True
    return False


def commit_paths(root: Path, paths: list[str], msg: str) -> bool:
    git(root, "add", "--", *paths)
    if git(root, "diff", "--cached", "--quiet", "--", *paths, check=False).returncode == 0:
        return False
    git(root, "commit", "-q", "-m", msg, "--", *paths)
    return True


_MSG_TAIL = ("\n\nscripts/glyph_store_sync.py（systemd guji-glyph-store-sync.timer，每 30 分钟）。\n"
             "db 不进 git，真源是 output/glyph_store/；feedback/ 只照抄现状提交，"
             "本脚本不生成不修改内容。")


def main(argv: list[str] | None = None) -> int:
    """一轮同步（2026-09-28 overview#234 改序，原来是「先导出、提交，再 pull」）：

    1. 人裁状态（feedback/、排除名单）照旧：持书锁 add/commit；
    2. **先 pull**，把别人推上来的 store 改动拿到手；
    3. 每本书：上游改过 store 就三方合并套进 db → 删除护栏 → 导出（`export_one`）；
    4. 提交 store、推送。推送成功后记下这次导出的 store 树，当下一轮三方合并的 base。
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path.home() / "guji-workspace"))
    ap.add_argument("--no-push", action="store_true", help="只提交，不 pull 不推")
    a = ap.parse_args(argv)
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
    store_rels = [store_rel(root, ws) for ws in books]
    restore_store(root, store_rels)

    # 1. 人裁状态：feedback/ 与排除名单**每本书都查**，写主体是控制台裁决（09-26 加）
    feedback_paths = [str((ws / rel).relative_to(root)) for ws in fb_books for rel in feedback_rel_paths(ws)]
    if feedback_paths:
        with acquire_feedback_lock(fb_books):
            if commit_paths(root, feedback_paths,
                            f"定时同步：人裁事件/裁决/绑定表/排除名单：{len(fb_books)} 本书检查、"
                            f"{len(feedback_paths)} 个路径纳入" + _MSG_TAIL):
                log("人裁状态已提交")

    # 2. 先拿上游
    online = not a.no_push and has_upstream(root)
    if online and not pull_upstream(root, store_rels):
        log("拉不到上游，本轮不导出（导出要以上游为准做合并）")
        return 1

    # 3. 合并 + 护栏 + 导出
    changed, blocked = [], []
    for ws in books:
        try:
            r = export_one(ws, root)
        except Exception as e:                      # noqa: BLE001 —— 一本书坏了不拖别的书
            log(f"{ws.name[:12]}: 导出失败 {type(e).__name__}: {e}")
            blocked.append(ws)
            continue
        (blocked if r["blocked"] else changed if r["exported"] else []).append(ws)
    glyph_paths = [store_rel(root, ws) for ws in changed]
    if glyph_paths:
        names = "、".join(ws.name.split("-", 1)[-1][:6] for ws in changed)
        if not commit_paths(root, glyph_paths, f"定时同步：字形库 store：{names}" + _MSG_TAIL):
            log("导出与已提交的一致，不提交")
    # 这轮 db 与之对齐的 store 树：推上去以后就是下一轮的 base（护栏拦下 / 出错的书不记）
    trees = {ws: tree_sha_head(root, ws) for ws in books if ws not in blocked}

    # 4. 推送
    ahead = git(root, "rev-list", "--count", "@{u}..HEAD", check=False).stdout.strip() if online else ""
    if not online or ahead in ("", "0"):
        for ws, t in trees.items():
            save_state(ws, store_tree=t)
        if not online and (glyph_paths or feedback_paths):
            log("已提交（--no-push / 没有上游）")
        return 1 if blocked else 0
    ps = git(root, "push", "-q", check=False)
    if ps.returncode == 0:
        for ws, t in trees.items():
            save_state(ws, store_tree=t)
        log(f"已提交并推送：{git(root, 'log', '--oneline', '-1').stdout.strip()}")
        return 1 if blocked else 0
    # 没推上去（上游这期间又有人推）：**不在本轮 pull 重试**——重试里 pull 一冲突就会退回上游，
    # 那时再记 base 等于把「没推上去的 db 刻例」当成上游已撤，下一轮会误撤。base 不动，下一轮
    # 先 pull 再按老 base 合并（已套过的是幂等的），30 分钟后自然推上去。
    log(f"推送失败，下一轮再推：{ps.stderr.strip()[:300]}")
    return 1


def tree_sha_head(root: Path, ws: Path) -> str | None:
    from open_guji_cv.clustering.store_merge import tree_sha
    return tree_sha(root, "HEAD", store_rel(root, ws))


if __name__ == "__main__":
    raise SystemExit(main())
