# -*- coding: utf-8 -*-
"""`guji snap pack`（云端用）：从 products 打包、写 manifest、做成孤儿提交推 `snap/…` 分支。

打包**只读** products，不拿跑批锁以外的任何东西；`_prev/`（格级复用用的上一代）不进包——
导到服务器以后它对应的是云端的上一代，不是服务器的，带过去反而误导格级复用。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import gitio
from .manifest import (CHUNK_BYTES, FORMAT, MANIFEST, MODES, ManifestError, branch_name, dumps,
                       safe_relpath, sha256_file, utc_stamp, validate, ws_key)

_PAGE_FILE = re.compile(r"^p(\d+)\.")


@dataclass
class Attachment:
    """随包带走的非产物文件：R 道预建的 `emb_*.npz`、书 yaml 之类。
    `root`=`cv`（落 cv 仓，相对仓根）或 `ws`（落书的工作区目录）。"""
    root: str
    dest: str
    src: Path | None = None
    url: str | None = None
    sha256: str | None = None
    size: int | None = None


@dataclass
class PackSpec:
    book: str
    products_root: Path
    ws_dir: Path
    steps: list[str] | None = None
    pages: list[int] | None = None          # None = 这几步现有的全部页（page_scope=full）
    mode: str = "replace-steps"
    supersedes: list[str] = field(default_factory=list)
    cv_commit: str | None = None
    compatible_with: list[str] = field(default_factory=list)
    param_overrides: dict[str, dict] = field(default_factory=dict)
    attachments: list[Attachment] = field(default_factory=list)
    glyph_fingerprint: str | None = None
    session: str | None = None
    note: str = ""
    stamp: str | None = None
    #: 服务器上还没有这个工作区目录时允许导入端新建（新书第一包，如全唐文 `qtw-draft`）。
    #: 缺省不许——找不到工作区多半是配错了 `--ws-root`，悄悄新建一个空目录只会掩盖问题。
    create_workspace: bool = False
    #: 允许导入后新鲜度变差（见 importer 模块头「防降级」）。只在明知服务器那份要被换掉时给。
    allow_downgrade: bool = False


def parse_pages(spec: str | None) -> list[int] | None:
    """`1-5,9` → [1..5, 9]；`all`/空 → None。命名页集（dev_set 等）由调用方先解析。"""
    if not spec or spec == "all":
        return None
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        lo, hi = int(a), int(b or a)
        out.update(range(lo, hi + 1))
    return sorted(out)


def _compact_manifest(path: Path) -> dict[str, dict]:
    """`_manifest.jsonl` 追加写、后写覆盖 → 每个 key 最后一条。"""
    out: dict[str, dict] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            d = json.loads(line)
            out[d["key"]] = d
    return out


def _gates_of(steps: list[str]) -> dict[str, str]:
    """{步: 它出口挂的闸}。读不到注册表（极简环境）就当没有闸。"""
    try:
        from .. import steps as _register  # noqa: F401 —— import 即注册全部 Step 与闸
        from ..core.step import STEPS
    except Exception:  # noqa: BLE001
        return {}
    return {s: STEPS[s].spec.gate.id for s in steps if s in STEPS and STEPS[s].spec.gate}


def _page_of(name: str) -> int | None:
    m = _PAGE_FILE.match(name)
    return int(m.group(1)) if m else None


def _cv_head(repo: Path) -> str | None:
    cp = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True)
    return cp.stdout.strip() if cp.returncode == 0 else None


def _pipeline_params(book: str, ws_dir: Path, steps: list[str]) -> tuple[dict, str | None]:
    """管线 yaml 的 `params:`（这条链对各步的覆盖）+ 书 yaml 的 sha256。读不到就空着——
    打包不该因为 manifest 少一栏信息失败。"""
    from .manifest import sha256_file as _sha
    yml = ws_dir / "books" / f"{book}.yaml"
    book_sha = _sha(yml) if yml.is_file() else None
    try:
        from ..core.book import load_book
        from ..core.pipeline import default_pipeline_id, load_pipeline
        bk = load_book(book, ws_dir / "books")
        pl = load_pipeline(default_pipeline_id(bk))
        pp = getattr(pl, "params", None) or {}
        out = {s: dict(pp[s]) for s in steps if s in pp}
        bp = getattr(bk, "params", None) or {}
        for s in steps:
            if s in bp:
                out.setdefault(s, {}).update(dict(bp[s]))
        return out, book_sha
    except Exception:  # noqa: BLE001
        return {}, book_sha


def _glyph_fp(ws_dir: Path) -> str | None:
    """算产物时用的那个库的指纹：设了 `GUJI_GLYPH_DB`（借库，如全唐文借四庫库）就认它，否则本书库。"""
    env = os.environ.get("GUJI_GLYPH_DB")
    db = Path(env) if env else ws_dir / "output" / "glyph.db"
    if not db.is_file():
        return None
    try:
        from ..steps.glyph_match import db_fingerprint
        return db_fingerprint(db)
    except Exception:  # noqa: BLE001
        return None


def build_tree(spec: PackSpec, tree_dir: Path, *, cv_repo: Path | None = None,
               now: datetime | None = None) -> dict:
    """把包内容写到 `tree_dir`（应不存在或为空），返回 manifest（也已写进 tree_dir）。"""
    if spec.mode not in MODES:
        raise ManifestError(f"mode 只能是 {'/'.join(MODES)}")
    attach_only = spec.mode == "attach-only"
    src = Path(spec.products_root) / spec.book
    if attach_only:
        if spec.steps:
            raise ManifestError("attach-only 包不带步（--steps 去掉）")
        avail = []
    elif not src.is_dir():
        raise FileNotFoundError(f"没有产物目录 {src}（只带附件请用 --mode attach-only）")
    else:
        avail = sorted(p.name for p in src.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))
    steps = [] if attach_only else list(spec.steps or avail)
    gates_added = []
    for sid, gid in _gates_of(steps).items():
        # 点名的步挂着闸、产物里又有闸的目录，就一起带上（2026-09-27 服务器实测：Z16 的 vol03/vol04 包
        # 只带 border_detect/column_warp/row_segment/cell_shrink 四步，导入后闸是旧的，下游整条判过期/阻塞）
        if gid not in steps and gid in avail:
            steps.insert(steps.index(sid) + 1, gid)
            gates_added.append(gid)
    missing = [s for s in steps if s not in avail]
    if missing:
        raise FileNotFoundError(f"{src} 下没有这些步：{', '.join(missing)}（有：{', '.join(avail)}）")
    want = set(spec.pages) if spec.pages is not None else None

    tree_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict] = {}
    step_info: dict[str, dict] = {}
    pages_seen: set[int] = set()
    for s in steps:
        out_dir = tree_dir / "products" / spec.book / s
        out_dir.mkdir(parents=True, exist_ok=True)
        entries = _compact_manifest(src / s / "_manifest.jsonl")
        kept_keys: set[str] = set()
        for f in sorted((src / s).iterdir()):
            if not f.is_file() or f.name == "_manifest.jsonl" or f.name.endswith(".tmp"):
                continue
            pg = _page_of(f.name)
            if want is not None and pg is not None and pg not in want:
                continue
            if pg is not None:
                pages_seen.add(pg)
            shutil.copy2(f, out_dir / f.name)
            kept_keys.add(f.name.rsplit(".json", 1)[0] if f.name.endswith(".json") else f.name)
        # 有文件的 key 全留；没文件的（failed/skipped 记录）只留选中页的——状态要跟过去，
        # 不然服务器上那页会从「失败」变「缺失」。
        kept_entries = [e for k, e in entries.items()
                        if k in kept_keys or want is None or _page_of(k + ".") in want]
        (out_dir / "_manifest.jsonl").write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in kept_entries), encoding="utf-8")
        st: dict[str, int] = {}
        for e in kept_entries:
            st[e.get("status", "ok")] = st.get(e.get("status", "ok"), 0) + 1
        step_info[s] = {
            "params_hash": sorted({e.get("params_hash") for e in kept_entries if e.get("params_hash")}),
            "code_revs": sorted({e.get("code_rev") for e in kept_entries if e.get("code_rev")}),
            "entries": st,
        }
        for f in sorted(out_dir.iterdir()):
            rel = f"products/{spec.book}/{s}/{f.name}"
            files[rel] = {"sha256": sha256_file(f), "size": f.stat().st_size}

    attachments = []
    for a in spec.attachments:
        if a.root not in ("cv", "ws"):
            raise ManifestError(f"附件 root 只能是 cv/ws：{a.root}")
        dest = safe_relpath(a.dest)
        if a.src is None:
            if not a.url or not a.sha256 or len(a.sha256) != 64:
                raise ManifestError(f"外链附件要给 url 和 sha256：{dest}")
            attachments.append({"root": a.root, "dest": dest, "url": a.url, "sha256": a.sha256,
                                "size": a.size, "parts": []})
            continue
        size = a.src.stat().st_size
        base = f"attach/{a.root}/{dest}"
        (tree_dir / base).parent.mkdir(parents=True, exist_ok=True)
        if size <= CHUNK_BYTES:
            shutil.copy2(a.src, tree_dir / base)
            parts = [base]
        else:
            parts = []
            with open(a.src, "rb") as fh:
                i = 0
                while True:
                    buf = fh.read(CHUNK_BYTES)
                    if not buf:
                        break
                    p = f"{base}.part{i:03d}"
                    (tree_dir / p).write_bytes(buf)
                    parts.append(p)
                    i += 1
        attachments.append({"root": a.root, "dest": dest, "sha256": sha256_file(a.src),
                            "size": size, "parts": parts})

    now = now or datetime.now(timezone.utc)
    stamp = spec.stamp or utc_stamp(now)
    wsk = ws_key(Path(spec.ws_dir).name)
    branch = branch_name(wsk, spec.book, stamp)
    pl_params, book_sha = _pipeline_params(spec.book, Path(spec.ws_dir), steps)
    params = {}
    for s in steps:
        ov = dict(pl_params.get(s, {}))
        ov.update(spec.param_overrides.get(s, {}))
        params[s] = {"params_hash": step_info[s]["params_hash"], "overrides": ov}
    cv_commit = spec.cv_commit or (_cv_head(cv_repo) if cv_repo else None)
    if not cv_commit:
        raise ManifestError("拿不到 cv 提交：给 --cv-commit，或在 cv 仓里跑")
    manifest = {
        "format": FORMAT,
        "id": branch[len("snap/"):],
        "branch": branch,
        "workspace": {"key": wsk, "dir": Path(spec.ws_dir).name, "create": bool(spec.create_workspace)},
        "book": spec.book,
        "steps": steps,
        "gates_added": gates_added,
        "pages": sorted(pages_seen),
        "page_scope": "none" if attach_only else ("full" if spec.pages is None else "subset"),
        "mode": spec.mode,
        "allow_downgrade": bool(spec.allow_downgrade),
        "supersedes": list(spec.supersedes),
        "cv": {"commit": cv_commit, "compatible_with": list(spec.compatible_with),
               "code_revs": {s: step_info[s]["code_revs"] for s in steps}},
        "params": params,
        "step_entries": {s: step_info[s]["entries"] for s in steps},
        "book_yaml_sha256": book_sha,
        "glyph_db_fingerprint": spec.glyph_fingerprint or _glyph_fp(Path(spec.ws_dir)),
        "created": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": spec.session or os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID")
        or os.environ.get("CLAUDE_CODE_SESSION_ID") or socket.gethostname(),
        "host": socket.gethostname(),
        "note": spec.note,
        "files": files,
        "attachments": attachments,
    }
    validate(manifest)
    (tree_dir / MANIFEST).write_text(dumps(manifest), encoding="utf-8")
    return manifest


def commit_and_push(ws_repo: Path, tree_dir: Path, manifest: dict, *, push: bool = True,
                    remote: str = "origin", git: gitio.GitRunner = gitio.default_git) -> str:
    """做成孤儿提交；`push=False` 时只在本地建 `refs/heads/<branch>`（演练/检查用）。"""
    msg = (f"快照 {manifest['id']}：{manifest['book']} {len(manifest['pages'])} 页 "
           f"{','.join(manifest['steps'])}（{manifest['mode']}）\n\n"
           f"cv {manifest['cv']['commit']}；guji snap pack 生成，内容见 manifest.json。"
           + (f"\n\n{manifest['note']}" if manifest.get("note") else ""))
    commit = gitio.commit_tree_from_dir(ws_repo, tree_dir, msg, git=git)
    if push:
        gitio.push_commit(ws_repo, commit, manifest["branch"], remote=remote, git=git)
    else:
        cp = git(ws_repo, ["update-ref", f"refs/heads/{manifest['branch']}", commit, ""])
        if cp.returncode != 0:
            raise gitio.GitError(f"本地分支已存在：{manifest['branch']}")
    return commit
