# -*- coding: utf-8 -*-
"""快照包格式 v1：manifest、分支名、工作区短 id、导入标记文件。"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

FORMAT = "guji-snap/1"
BRANCH_PREFIX = "snap/"
MANIFEST = "manifest.json"
MODES = ("replace-steps", "display-only")
#: GitHub 单文件 50 MB 起警告、100 MB 硬拒；留余量切 45 MB 一块。
CHUNK_BYTES = 45 * 1024 * 1024

#: 书目录里导入相关的隐藏文件（都在 `products/<book>/` 下，`products/` 本来就不进 git）。
MARKS_NAME = ".snap_marks.json"         # display-only 标记：部署器过期步队列据此跳过
IMPORTS_NAME = ".snap_imports.jsonl"    # 本书的导入流水
BACKUP_DIR = ".snap_backup"             # 被覆盖的 step 目录，留最近 BACKUP_KEEP 份
STAGING_PREFIX = ".snap_staging-"
BACKUP_KEEP = 2

#: 附件只许落到这些位置。包是无人值守导入的，附件不能碰代码——cv 仓里只许 `models/`
#: （R 道预建的 `emb_*.npz` 就在 `models/<ckpt>/` 下），工作区里只许数据目录与 `.gitignore`。
ATTACH_ALLOWED = {"cv": ("models/",),
                  "ws": ("books/", "corpus/", "config/", "cache/", "models/", "data_full/", ".gitignore")}

_WS_ID = re.compile(r"^([0-9a-z]{8,16})-")
_SAFE = re.compile(r"^[0-9A-Za-z._-]+$")


class ManifestError(ValueError):
    """manifest 缺字段、字段不合法或路径越界。"""


def ws_key(dirname: str) -> str:
    """工作区目录 → 分支里用的短 id。`96mid1ogzk-欽定四庫…` → `96mid1ogzk`；
    没有 book-index id 前缀的（`qtw-draft`）用整个目录名。"""
    m = _WS_ID.match(dirname)
    return m.group(1) if m else dirname


def utc_stamp(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M")


def branch_name(ws: str, book: str, stamp: str) -> str:
    for part, what in ((ws, "工作区短 id"), (book, "书 id"), (stamp, "时戳")):
        if not _SAFE.match(part):
            raise ManifestError(f"{what} 不能进分支名：{part!r}")
    return f"{BRANCH_PREFIX}{ws}/{book}/{stamp}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_relpath(rel: str) -> str:
    """包里的路径只许是相对、无 `..`、无反斜杠的 posix 路径。"""
    if not rel or rel.startswith("/") or "\\" in rel or any(p in ("", ".", "..") for p in rel.split("/")):
        raise ManifestError(f"包内路径不合法：{rel!r}")
    return rel


def validate(m: dict) -> dict:
    """查 manifest 的形状。返回原 dict；不合法抛 ManifestError。"""
    if m.get("format") != FORMAT:
        raise ManifestError(f"不认识的格式 {m.get('format')!r}（本程序只认 {FORMAT}）")
    for k in ("id", "book", "steps", "mode", "files", "cv", "workspace", "created"):
        if k not in m:
            raise ManifestError(f"manifest 缺字段 {k}")
    if m["mode"] not in MODES:
        raise ManifestError(f"mode 只能是 {'/'.join(MODES)}，不是 {m['mode']!r}")
    if not _SAFE.match(m["book"]):
        raise ManifestError(f"书 id 不合法：{m['book']!r}")
    for s in m["steps"]:
        if not _SAFE.match(s) or s.startswith("."):
            raise ManifestError(f"step id 不合法：{s!r}")
    if not m["cv"].get("commit"):
        raise ManifestError("manifest 没写 cv.commit")
    prefix = f"products/{m['book']}/"
    for rel, meta in m["files"].items():
        safe_relpath(rel)
        if not rel.startswith(prefix) or rel[len(prefix):].split("/", 1)[0] not in m["steps"]:
            raise ManifestError(f"文件不在声明的书/步里：{rel}")
        if not isinstance(meta, dict) or len(meta.get("sha256", "")) != 64:
            raise ManifestError(f"文件缺 sha256：{rel}")
    for a in m.get("attachments", []):
        if a.get("root") not in ("cv", "ws"):
            raise ManifestError(f"附件 root 只能是 cv/ws：{a}")
        dest = safe_relpath(a.get("dest", ""))
        if not any(dest == p or (p.endswith("/") and dest.startswith(p)) for p in ATTACH_ALLOWED[a["root"]]):
            raise ManifestError(f"附件不许落到 {a['root']}:{dest}（只许 {', '.join(ATTACH_ALLOWED[a['root']])}）")
        if len(a.get("sha256", "")) != 64:
            raise ManifestError(f"附件缺 sha256：{a.get('dest')}")
        for p in a.get("parts", []):
            safe_relpath(p)
            if not p.startswith("attach/"):
                raise ManifestError(f"附件分块不在 attach/ 下：{p}")
        if not a.get("parts") and not a.get("url"):
            raise ManifestError(f"附件既没有分块也没有 url：{a.get('dest')}")
    return m


def dumps(m: dict) -> str:
    return json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


# ── 书目录里的导入标记 ────────────────────────────────────────────────
def read_marks(products_root: Path, book: str) -> dict:
    p = Path(products_root) / book / MARKS_NAME
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_marks(products_root: Path, book: str, marks: dict) -> None:
    p = Path(products_root) / book / MARKS_NAME
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(marks, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def display_only_steps(products_root: Path, book: str) -> set[str]:
    """这本书哪些步是 display-only 包导进来的（只看不算：不许在服务器上重算）。"""
    return set((read_marks(products_root, book).get("display_only") or {}).keys())


def append_import_log(products_root: Path, book: str, row: dict) -> None:
    p = Path(products_root) / book / IMPORTS_NAME
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **row}
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
