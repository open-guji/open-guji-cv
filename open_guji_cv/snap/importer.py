# -*- coding: utf-8 -*-
"""`guji snap import <分支> [--dry-run]`（服务器用，也能手动跑）。

顺序（任务书 §3）：

1. 拉包（显式 refspec、`--depth 1`），读 manifest、查格式；
2. 解到书目录下的暂存区，**逐文件校验 sha256**（多一个、少一个、错一个都拒）；
3. 查书级跑批锁（`core.runlock` 同一把 flock）——被占就 `LOCKED`，下轮再试；
4. 查 cv 版本兼容：包的 `cv.commit` 是服务器 HEAD 的祖先，或 `cv.compatible_with`
   里有一个是——都不是就 `INCOMPATIBLE`（服务器部署跟上来以后下一轮自然通过）；
5. **持锁**：被覆盖的 step 目录整个挪进 `products/<book>/.snap_backup/<时戳>__<包>/`
   （每本书留最近 `BACKUP_KEEP` 份）、暂存目录 `os.replace` 到位——同一文件系统上的改名，
   读的人要么看到旧目录、要么看到新目录；中途失败按已换的步逆序换回；
6. **防降级**：持锁量一次换上后的新鲜度，包里任一步「新鲜」页数比导入前少就整包换回、报
   `DOWNGRADE`（终态）——无人值守的导入不许把服务器上新鲜的产物换成过期的（典型：服务器已在
   更新的代码上重算过，云端包是旧提交算的）。display-only 包不查（本来就预期过期）；
   manifest `allow_downgrade: true`（`pack --allow-downgrade`）或 `import --force` 可放行；
7. 写 display-only 标记（`.snap_marks.json`）与本书导入流水（`.snap_imports.jsonl`）。

`page_scope=subset` 的包（只含部分页）不整目录替换：先复制现有 step 目录，覆盖包里那几页的
文件，`_manifest.jsonl` 追加包里的条目（追加写、后写覆盖是它本来的语义），再整目录换上。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tarfile
import tempfile
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import gitio
from .manifest import (BACKUP_DIR, BACKUP_KEEP, MANIFEST, STAGING_PREFIX, ManifestError, append_import_log,
                       read_marks, safe_relpath, sha256_file, validate, write_marks, ws_key)

IMPORTED = "imported"
WOULD_IMPORT = "would_import"
FETCH_FAILED = "fetch_failed"
BAD_MANIFEST = "bad_manifest"
NO_WORKSPACE = "no_workspace"
SUPERSEDED = "superseded"
SHA_MISMATCH = "sha_mismatch"
LOCKED = "locked"
INCOMPATIBLE = "incompatible"
FAILED = "failed"
DOWNGRADE = "downgrade"

#: 这些状态下一轮还会再试（锁放了、服务器部署跟上了、工作区挂上了……）；
#: 其余是终态，同一提交不再重试（分支提交变了才会再看）。
RETRYABLE = frozenset({FETCH_FAILED, NO_WORKSPACE, LOCKED, INCOMPATIBLE, FAILED})


@dataclass
class ImportResult:
    status: str
    branch: str
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"status": self.status, "branch": self.branch, **self.detail}


# ── 可注入的外部动作 ─────────────────────────────────────────────────
def default_url_fetch(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=600) as r, open(dest, "wb") as f:  # noqa: S310
        shutil.copyfileobj(r, f, 1 << 20)


def default_freshness(ws_dir: Path, book: str, pages: list[int] | None) -> dict:
    """`guji status` 同一套逻辑，进程内跑：{step: {fresh: n, stale: n, …}}。
    临时把 `GUJI_WORKSPACE` 指到这个工作区、摘掉 `GUJI_PRODUCTS_DIR`，跑完还原。"""
    keys = ("GUJI_WORKSPACE", "GUJI_PRODUCTS_DIR")
    saved = {k: os.environ.get(k) for k in keys}
    os.environ["GUJI_WORKSPACE"] = str(ws_dir)
    os.environ.pop("GUJI_PRODUCTS_DIR", None)
    try:
        from ..core.book import load_book
        from ..core.engine import Engine
        from ..core.pipeline import default_pipeline_id, load_pipeline
        bk = load_book(book, Path(ws_dir) / "books")
        eng = Engine(bk, load_pipeline(default_pipeline_id(bk)), log=lambda s: None)
        st = eng.status(pages=pages if pages else bk.resolve_pages("all"))
        return {sid: dict(d["counts"]) for sid, d in st["steps"].items()}
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _safe_freshness(fn, ws_dir, book, pages) -> dict:
    try:
        return fn(ws_dir, book, pages)
    except Exception as e:  # noqa: BLE001 —— 量不出新鲜度不拖垮导入
        return {"error": f"{type(e).__name__}: {e}"}


# ── 各环节 ───────────────────────────────────────────────────────────
def find_workspace(ws_roots: list[Path], key: str, dirname: str | None = None) -> Path | None:
    """按目录名、再按短 id 找书的工作区目录。`ws_roots` 可以是仓根（下面好几个书目录），
    也可以直接是某个书目录。"""
    for root in ws_roots:
        root = Path(root)
        if root.is_dir() and (root.name == dirname or ws_key(root.name) == key) and (root / "books").is_dir():
            return root
        if dirname and (root / dirname).is_dir():
            return root / dirname
        if root.is_dir():
            for d in sorted(root.iterdir()):
                if d.is_dir() and ws_key(d.name) == key:
                    return d
    return None


def read_manifest(ws_repo: Path, ref: str, git: gitio.GitRunner = gitio.default_git) -> dict:
    try:
        m = json.loads(gitio.show_file(ws_repo, ref, MANIFEST, git))
    except (gitio.GitError, ValueError) as e:
        raise ManifestError(f"读不出 manifest：{e}") from e
    return validate(m)


def extract_and_verify(tar_bytes: bytes, m: dict, staging: Path,
                       url_fetch: Callable[[str, Path], None] = default_url_fetch) -> list[str]:
    """解包到 `staging` 并逐文件校验。返回问题清单（空 = 通过）。
    附件拼好/下载好的整文件放 `staging/_attach/<root>/<dest>`。"""
    problems: list[str] = []
    want = m["files"]
    parts = {p for a in m.get("attachments", []) for p in a.get("parts", [])}
    seen: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tf:
        for mem in tf:
            if mem.isdir():
                continue
            name = mem.name
            if name == MANIFEST:
                continue
            try:
                safe_relpath(name)
            except ManifestError as e:
                problems.append(str(e))
                continue
            if not mem.isfile():
                problems.append(f"包里有非普通文件：{name}")
                continue
            if name not in want and name not in parts:
                problems.append(f"manifest 没登记的文件：{name}")
                continue
            dest = staging / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(mem)
            with open(dest, "wb") as f:
                shutil.copyfileobj(src, f, 1 << 20)
            seen.add(name)
    for rel, meta in want.items():
        if rel not in seen:
            problems.append(f"缺文件：{rel}")
        elif sha256_file(staging / rel) != meta["sha256"]:
            problems.append(f"sha256 对不上：{rel}")
    for a in m.get("attachments", []):
        full = staging / "_attach" / a["root"] / a["dest"]
        full.parent.mkdir(parents=True, exist_ok=True)
        try:
            if a.get("parts"):
                missing = [p for p in a["parts"] if p not in seen]
                if missing:
                    problems.append(f"附件缺分块：{', '.join(missing)}")
                    continue
                with open(full, "wb") as out:
                    for p in a["parts"]:
                        with open(staging / p, "rb") as fh:
                            shutil.copyfileobj(fh, out, 1 << 20)
            else:
                url_fetch(a["url"], full)
        except Exception as e:  # noqa: BLE001
            problems.append(f"附件取不到：{a['dest']}：{type(e).__name__}: {e}")
            continue
        if sha256_file(full) != a["sha256"]:
            problems.append(f"附件 sha256 对不上：{a['root']}:{a['dest']}")
    return problems


def check_cv(cv_repo: Path, m: dict, git: gitio.GitRunner = gitio.default_git,
             remote: str = "origin") -> tuple[bool, dict]:
    head = gitio.rev_parse(cv_repo, "HEAD", git)
    cands = [m["cv"]["commit"], *m["cv"].get("compatible_with", [])]
    tried = {}
    for c in cands:
        r = gitio.is_ancestor(cv_repo, c, "HEAD", git)
        if r is None:          # 本地没有这个提交：拉一次再判（服务器 clone 可能落后）
            git(cv_repo, ["fetch", "-q", remote, c])
            r = gitio.is_ancestor(cv_repo, c, "HEAD", git)
        tried[c] = {True: "是 HEAD 的祖先", False: "不是 HEAD 的祖先", None: "服务器找不到这个提交"}[r]
        if r:
            return True, {"server_head": head, "via": c, "checked": tried}
    return False, {"server_head": head, "checked": tried}


def probe_lock(products_root: Path, book: str) -> dict | None:
    """只探测不占用：有人持锁返回持有者信息（可能为空 dict），没人返回 None。"""
    from ..core.runlock import _try_lock, read_holder
    path = Path(products_root) / book / ".run.lock"
    if not path.exists():
        return None
    fh = open(path, "a+", encoding="utf-8")
    try:
        if _try_lock(fh, blocking=False):
            return None
        return read_holder(path) or {}
    finally:
        fh.close()


def _prune_backups(book_dir: Path, keep: int = BACKUP_KEEP) -> list[str]:
    root = book_dir / BACKUP_DIR
    if not root.is_dir():
        return []
    dirs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.name)
    gone = []
    for d in dirs[:-keep] if keep else dirs:
        shutil.rmtree(d, ignore_errors=True)
        gone.append(d.name)
    return gone


def _merge_subset(final: Path, new: Path, out: Path) -> None:
    """subset 包：现有 step 目录 + 包里那几页 → `out`。"""
    shutil.copytree(final, out)
    for f in new.iterdir():
        if f.is_file() and f.name != "_manifest.jsonl":
            shutil.copy2(f, out / f.name)
    add = (new / "_manifest.jsonl").read_text(encoding="utf-8") if (new / "_manifest.jsonl").is_file() else ""
    if add:
        with open(out / "_manifest.jsonl", "a", encoding="utf-8") as fh:
            fh.write(add if add.endswith("\n") else add + "\n")


def _swap_in(m: dict, staging: Path, book_dir: Path, backup_dir: Path) -> list[str]:
    """持锁时调用：逐步把旧目录挪进备份、新目录换上。失败逆序换回再抛。返回备份了哪些步。"""
    book = m["book"]
    done: list[tuple[str, bool]] = []
    backed: list[str] = []
    try:
        for s in m["steps"]:
            final = book_dir / s
            new = staging / "products" / book / s
            if not new.is_dir():
                new.mkdir(parents=True)
            if m.get("page_scope") == "subset" and final.is_dir():
                merged = staging / "_merged" / s
                merged.parent.mkdir(parents=True, exist_ok=True)
                _merge_subset(final, new, merged)
                new = merged
            moved = False
            if final.exists():
                backup_dir.mkdir(parents=True, exist_ok=True)
                os.replace(final, backup_dir / s)
                moved = True
            done.append((s, moved))
            os.replace(new, final)
            if moved:
                backed.append(s)
    except BaseException:
        for s, moved in reversed(done):
            final = book_dir / s
            if final.exists() and (not moved or (backup_dir / s).exists()):
                shutil.rmtree(final, ignore_errors=True)
            if moved and (backup_dir / s).exists():
                os.replace(backup_dir / s, final)
        raise
    return backed


def _place_attachments(m: dict, staging: Path, ws_dir: Path, cv_repo: Path, backup_dir: Path) -> list[str]:
    placed = []
    for a in m.get("attachments", []):
        base = cv_repo if a["root"] == "cv" else ws_dir
        dest = Path(base) / a["dest"]
        src = staging / "_attach" / a["root"] / a["dest"]
        if dest.is_file() and sha256_file(dest) == a["sha256"]:
            continue
        if Path(a["dest"]).name == ".gitignore" and dest.is_file():
            # .gitignore 按行合并：只追加本地没有的行，不删本地的行（2026-09-27 服务器实测：整文件覆盖把
            # 本地的 `*` 换掉，qtw-draft/data_full 的 520 张原图一下子全变 untracked）
            have = dest.read_text(encoding="utf-8").splitlines()
            seen = {ln.strip() for ln in have}
            add = [ln for ln in src.read_text(encoding="utf-8").splitlines()
                   if ln.strip() and ln.strip() not in seen]
            if not add:
                continue
            bk = backup_dir / "_attach" / a["root"] / a["dest"]
            bk.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, bk)
            tmp = dest.with_name(dest.name + ".snap-tmp")
            tmp.write_text("\n".join(have + add) + "\n", encoding="utf-8")
            os.replace(tmp, dest)
            placed.append(f"{a['root']}:{a['dest']}")
            continue
        if dest.exists():
            bk = backup_dir / "_attach" / a["root"] / a["dest"]
            bk.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, bk)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".snap-tmp")
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
        placed.append(f"{a['root']}:{a['dest']}")
    return placed


def downgraded_steps(before: dict, after: dict, steps: list[str]) -> dict[str, str]:
    """包里哪些步导入后「新鲜」页数比导入前少。任一边量不出（error）就不判——不因为
    量法坏了挡住导入，也不因为量法坏了放过降级（记录里两边都会写出来）。"""
    if "error" in before or "error" in after:
        return {}
    out = {}
    for s in steps:
        b = (before.get(s) or {}).get("fresh", 0)
        a = (after.get(s) or {}).get("fresh", 0)
        if a < b:
            out[s] = f"新鲜 {b} → {a}"
    return out


def _swap_back(m: dict, book_dir: Path, backup_dir: Path, backed: list[str], placed: list[str],
               ws_dir: Path, cv_repo: Path) -> None:
    """撤回一次已换上的导入（持锁时调用）：包里的步删掉，备份挪回；附件有备份的还原、没有的删掉。"""
    for s in m["steps"]:
        final = book_dir / s
        if final.exists():
            shutil.rmtree(final)
        if s in backed:
            os.replace(backup_dir / s, final)
    for tag in placed:
        root, _, dest = tag.partition(":")
        target = Path(cv_repo if root == "cv" else ws_dir) / dest
        bk = backup_dir / "_attach" / root / dest
        if bk.is_file():
            shutil.copy2(bk, target)
        else:
            target.unlink(missing_ok=True)


def import_pack(branch: str, *, ws_repo: Path, ws_roots: list[Path], cv_repo: Path,
                remote: str = "origin", dry_run: bool = False, force: bool = False,
                superseded_by: str | None = None, fetch: bool = True,
                git: gitio.GitRunner = gitio.default_git,
                freshness_fn: Callable[[Path, str, list[int] | None], dict] = default_freshness,
                url_fetch: Callable[[str, Path], None] = default_url_fetch) -> ImportResult:
    ref = gitio.remote_ref(branch, remote)
    if fetch:
        try:
            gitio.fetch_branches(ws_repo, [branch], remote, git)
        except gitio.GitError as e:
            return ImportResult(FETCH_FAILED, branch, {"error": str(e)})
    commit = gitio.rev_parse(ws_repo, ref, git)
    if commit is None:
        return ImportResult(FETCH_FAILED, branch, {"error": f"本地没有 {ref}"})
    try:
        m = read_manifest(ws_repo, ref, git)
    except ManifestError as e:
        return ImportResult(BAD_MANIFEST, branch, {"commit": commit, "error": str(e)})
    base = {"commit": commit, "pack": m["id"], "book": m["book"], "mode": m["mode"],
            "steps": m["steps"], "pages": len(m.get("pages", [])), "page_scope": m.get("page_scope"),
            "pack_cv": m["cv"]["commit"]}
    if superseded_by and not force:
        return ImportResult(SUPERSEDED, branch, {**base, "superseded_by": superseded_by})
    ws_dir = find_workspace(ws_roots, m["workspace"]["key"], m["workspace"].get("dir"))
    if ws_dir is None and m["workspace"].get("create") and ws_roots:
        # 新书第一包：在第一个 ws 根下按包里的目录名新建（名字已由 safe_relpath 校验）
        name = safe_relpath(m["workspace"].get("dir") or m["workspace"]["key"])
        if "/" not in name and Path(ws_roots[0]).is_dir():
            ws_dir = Path(ws_roots[0]) / name
            if dry_run:
                base["workspace_would_create"] = str(ws_dir)
            else:
                (ws_dir / "books").mkdir(parents=True, exist_ok=True)
                base["workspace_created"] = True
    if ws_dir is None:
        return ImportResult(NO_WORKSPACE, branch, {**base, "workspace": m["workspace"],
                                                   "searched": [str(r) for r in ws_roots]})
    base["workspace"] = ws_dir.name
    products_root = ws_dir / "products"
    book_dir = products_root / m["book"]
    if dry_run:     # 演练不在书目录里留任何东西（连空的 products/<book> 都不建）
        staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX))
    else:           # 真导入暂存在书目录里：与最终位置同一文件系统，os.replace 才是原子改名
        book_dir.mkdir(parents=True, exist_ok=True)
        staging = book_dir / f"{STAGING_PREFIX}{uuid.uuid4().hex[:8]}"
    try:
        staging.mkdir(exist_ok=True)
        try:
            tar = gitio.archive_tar(ws_repo, ref, git)
        except gitio.GitError as e:
            return ImportResult(FETCH_FAILED, branch, {**base, "error": str(e)})
        problems = extract_and_verify(tar, m, staging, url_fetch)
        if problems:
            return ImportResult(SHA_MISMATCH, branch, {**base, "problems": problems[:20],
                                                       "n_problems": len(problems)})
        holder = probe_lock(products_root, m["book"])
        if holder is not None:
            return ImportResult(LOCKED, branch, {**base, "holder": holder})
        ok, cvd = check_cv(cv_repo, m, git, remote)
        base["cv_check"] = cvd
        if not ok:
            return ImportResult(INCOMPATIBLE, branch, base)
        # 新鲜度只量包里的页：`resolve_pages("all")` 是按原图目录数的，原图不在（或多于包）时会量偏
        pages = list(m.get("pages") or []) or None
        if dry_run:
            return ImportResult(WOULD_IMPORT, branch, {
                **base, "files": len(m["files"]), "attachments": len(m.get("attachments", [])),
                "plan": [f"备份并替换 products/{m['book']}/{s}" for s in m["steps"]]
                + (["打 display-only 标记：" + ",".join(m["steps"])] if m["mode"] == "display-only" else [])})
        before = _safe_freshness(freshness_fn, ws_dir, m["book"], pages)
        from ..core.runlock import RunLockHeld, book_run_lock
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        backup_dir = book_dir / BACKUP_DIR / f"{stamp}__{m['id'].replace('/', '_')}"
        guard = m["mode"] != "display-only" and not m.get("allow_downgrade") and not force
        try:
            with book_run_lock(m["book"], products=products_root, note=f"snap import {m['id']}"):
                backed = _swap_in(m, staging, book_dir, backup_dir)
                placed: list[str] = []
                try:
                    placed = _place_attachments(m, staging, ws_dir, cv_repo, backup_dir)
                    after = _safe_freshness(freshness_fn, ws_dir, m["book"], pages)
                    worse = downgraded_steps(before, after, m["steps"]) if guard else {}
                    if not worse:
                        marks = read_marks(products_root, m["book"])
                        do = marks.setdefault("display_only", {})
                        for s in m["steps"]:
                            if m["mode"] == "display-only":
                                do[s] = {"pack": m["id"], "commit": commit, "at": stamp}
                            else:
                                do.pop(s, None)
                        write_marks(products_root, m["book"], marks)
                except BaseException:
                    _swap_back(m, book_dir, backup_dir, backed, placed, ws_dir, cv_repo)
                    raise
                if worse:
                    _swap_back(m, book_dir, backup_dir, backed, placed, ws_dir, cv_repo)
                    shutil.rmtree(backup_dir, ignore_errors=True)
                    return ImportResult(DOWNGRADE, branch, {
                        **base, "downgraded": worse, "freshness_before": before,
                        "freshness_after_rolled_back": after})
                append_import_log(products_root, m["book"], {
                    "pack": m["id"], "branch": branch, "commit": commit, "mode": m["mode"],
                    "steps": m["steps"], "page_scope": m.get("page_scope"),
                    "backup": backup_dir.name if backed else None})
                pruned = _prune_backups(book_dir)
        except RunLockHeld as e:
            return ImportResult(LOCKED, branch, {**base, "holder": e.holder})
        return ImportResult(IMPORTED, branch, {
            **base, "backup": str(backup_dir.relative_to(ws_dir)) if backed else None,
            "backed_up_steps": backed, "attachments_placed": placed, "pruned_backups": pruned,
            "freshness_before": before, "freshness_after": after})
    except Exception as e:  # noqa: BLE001
        return ImportResult(FAILED, branch, {**base, "error": f"{type(e).__name__}: {e}"})
    finally:
        shutil.rmtree(staging, ignore_errors=True)
