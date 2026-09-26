# -*- coding: utf-8 -*-
"""书级跑批锁与产物快照（2026-09-26，overview `进度/并行分工.md` §三）。

**跑批锁**：同一个产物目录里同一本书，同一时刻只许一个 `guji pipeline/step` 在写。
此前靠「起跑批前先查有没有别人在跑」的纪律，实测挡不住——两个会话先后重跑 vol02，
下游在半截状态上跑了一轮，结果作废。锁文件在 `products_root()/<book>/.run.lock`：

- 用 `flock`（Windows 用 `msvcrt.locking`），**进程一死锁就放**，不会留死锁；
- 锁跟着产物目录走：沙箱（`GUJI_PRODUCTS_DIR=$SCRATCH/products`）与正式目录互不相干，
  沙箱里怎么跑都不跟正式跑批抢；
- 抢不到就报持有者（pid、主机、命令、开始时间），默认不等；`--wait` 才排队；
- `GUJI_NO_RUN_LOCK=1` 可关（只给确知在做什么的场合）。

**快照**：把一本书若干步的数值产物原样拷到 `products_snap/<book>/<名>/`，目录结构与
`products/` 相同，下游用 `GUJI_PRODUCTS_DIR=<快照目录>` 就能读——上游再怎么重跑，
下游手里那份不变。拷之前先拿同一把锁，不会拷到跑了一半的目录。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

LOCK_NAME = ".run.lock"
SNAP_REL = "products_snap"


class RunLockHeld(RuntimeError):
    """别的进程正持有这本书的跑批锁。"""

    def __init__(self, path: Path, holder: dict | None):
        self.path = path
        self.holder = holder or {}
        h = self.holder
        who = (f"pid {h.get('pid')}@{h.get('host')}，{h.get('started')} 起，命令：{h.get('cmd')}"
               if h else "持有者信息读不到")
        super().__init__(f"这本书正有别的跑批在写 {path.parent}（{who}）。"
                         f"等它跑完再来，或加 --wait 排队；试验请用 GUJI_PRODUCTS_DIR 指到沙箱。")


def lock_path(book_id: str, products: Path | None = None) -> Path:
    from .workspace import products_root
    return (products or products_root()) / book_id / LOCK_NAME


def _try_lock(fh, blocking: bool) -> bool:
    if os.name == "nt":
        import msvcrt
        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), mode, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return True
    except OSError:
        return False


def read_holder(path: Path) -> dict | None:
    try:
        txt = path.read_text(encoding="utf-8").strip()
        return json.loads(txt) if txt else None
    except (OSError, ValueError):
        return None


@contextmanager
def book_run_lock(book_id: str, *, products: Path | None = None, wait: bool = False,
                  note: str | None = None):
    """持有 `<products>/<book>/.run.lock` 期间独占这本书的产物目录。"""
    if os.environ.get("GUJI_NO_RUN_LOCK") == "1":
        yield None
        return
    path = lock_path(book_id, products)
    path.parent.mkdir(parents=True, exist_ok=True)
    # a+：不截断，抢不到锁时还能读出持有者
    fh = open(path, "a+", encoding="utf-8")
    try:
        if not _try_lock(fh, blocking=False):
            if not wait:
                raise RunLockHeld(path, read_holder(path))
            h = read_holder(path) or {}
            print(f"等待跑批锁：pid {h.get('pid')} 正在跑 {h.get('cmd')}", file=sys.stderr, flush=True)
            _try_lock(fh, blocking=True)
        holder = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "cmd": " ".join(sys.argv[1:]) or sys.argv[0],
            "started": datetime.now().isoformat(timespec="seconds"),
            "note": note,
        }
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(holder, ensure_ascii=False))
        fh.flush()
        try:
            yield holder
        finally:
            try:
                fh.seek(0)
                fh.truncate()
                fh.flush()
            except OSError:
                pass
    finally:
        fh.close()  # 关闭即放锁


def snapshots_root() -> Path:
    from .workspace import _resolve
    return _resolve("GUJI_SNAP_DIR", SNAP_REL)


def make_snapshot(book_id: str, steps: list[str] | None = None, name: str | None = None, *,
                  products: Path | None = None, dest_root: Path | None = None,
                  code_rev: str | None = None, lock: bool = True) -> Path:
    """拷 `<products>/<book>/<step>/` 到 `<dest_root>/<book>/<name>/<book>/<step>/`。

    返回可直接给 `GUJI_PRODUCTS_DIR` 用的目录（`<dest_root>/<book>/<name>`），
    里面另有 `SNAPSHOT.json` 记来源、commit、各步文件数。
    """
    from .workspace import products_root
    src_root = products or products_root()
    book_dir = src_root / book_id
    if not book_dir.is_dir():
        raise FileNotFoundError(f"没有产物目录 {book_dir}")
    avail = sorted(p.name for p in book_dir.iterdir() if p.is_dir())
    use = steps or avail
    missing = [s for s in use if s not in avail]
    if missing:
        raise FileNotFoundError(f"{book_dir} 下没有这些步：{', '.join(missing)}（有：{', '.join(avail)}）")
    if code_rev is None:
        from .engine import git_rev
        code_rev = git_rev()
    name = name or f"{time.strftime('%Y%m%d-%H%M')}-{code_rev or 'norev'}"
    out = (dest_root or snapshots_root()) / book_id / name
    if out.exists():
        raise FileExistsError(f"快照已存在：{out}")

    def _copy() -> dict:
        counts = {}
        for s in use:
            shutil.copytree(book_dir / s, out / book_id / s)
            counts[s] = sum(1 for p in (out / book_id / s).rglob("*") if p.is_file())
        return counts

    if lock:
        with book_run_lock(book_id, products=src_root, note=f"snapshot → {out}"):
            counts = _copy()
    else:
        counts = _copy()
    meta = {
        "book": book_id, "name": name, "steps": use, "files": counts,
        "source": str(book_dir), "code_rev": code_rev,
        "created": datetime.now().isoformat(timespec="seconds"),
        "host": socket.gethostname(),
    }
    (out / "SNAPSHOT.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
