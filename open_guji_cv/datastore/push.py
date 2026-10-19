"""写入切换后（GUJI-608）的读写：中心库是真源，工作区目录是它的一份工作副本。

    guji db pull -w <工作区> --full    # 人裁、台账、字形库、配置、册 yaml 从中心库还原进工作区本身
    …照常跑 cv（控制台、step、H 道）…
    guji db push -w <工作区>           # 把工作区里的改动写回中心库

**push 先比版本号**：``pull --full`` 在工作区根写 ``.central.json``（分支、rev）。push 在拿到库锁后
查这个工作区在那个 rev 之后有没有别人写过；有就整次拒绝，要先重新 pull（同 git 的 non-fast-forward），
所以两个会话不会互相冲掉。只追加的台账（events、consumed、anchors）少了行照旧拒绝；
整个文件没了也拒绝（多半是没 pull 全），确认是真删再加 ``--allow-delete``。

还原、写回的范围相同：``workspace.yaml``、``books/``、``feedback/``、``review/``、``config/``、
``output/glyph_store/`` 下 ``scope.classify`` 认的文件。原图、products、cache 不在中心库，照旧从 git／本地来。
新刻例图、锚图在写库之前先经 Worker 传进 R2（只增不改，已有跳过）。
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .scope import classify, sha256

PREFIXES = ("books/", "feedback/", "review/", "config/", "output/glyph_store/")
META = ".central.json"


class StaleBase(RuntimeError):
    pass


class FileDeleteRefused(RuntimeError):
    pass


def _walk(ws_dir: Path):
    """工作区里归中心库管的文件：(相对路径, 绝对路径)。"""
    ws_dir = Path(ws_dir)
    if (ws_dir / "workspace.yaml").exists():
        yield "workspace.yaml", ws_dir / "workspace.yaml"
    for pre in PREFIXES:
        root = ws_dir / pre.rstrip("/")
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file():
                rel = p.relative_to(ws_dir).as_posix()
                if classify(rel) is not None:
                    yield rel, p


def scan_dir(ws_dir: Path):
    from .scope import scan_files
    items = [(rel, (lambda p=p: p.read_bytes())) for rel, p in _walk(ws_dir)]
    return scan_files(items, Path(ws_dir).name)


def read_meta(ws_dir: Path) -> dict | None:
    p = Path(ws_dir) / META
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def write_meta(ws_dir: Path, **kw) -> None:
    meta = {**kw, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (Path(ws_dir) / META).write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def pull_full(src, ws_dir: Path, cache=None, bucket: str = "main", force: bool = False) -> dict:
    """把中心库里这个工作区的全部文件还原进工作区目录本身。

    库里有的文件覆盖；本地有、库里没有、又归中心库管的文件删掉（镜像；刻例图除外，没被引用的图无害）；
    别的文件不碰。``.central.json`` 记下 rev。本地有没 push 的改动时拒绝，除非 ``force``。
    """
    from .materialize import materialize
    from .pull import workspace_id
    ws_dir = Path(ws_dir)
    ws = workspace_id(ws_dir)
    if not force:
        dirty = local_changes(src, ws_dir, ws, missing=read_meta(ws_dir) is not None)
        if dirty:
            raise SystemExit(f"工作区有 {len(dirty)} 个文件改了还没 push（如 {dirty[:3]}）；"
                             f"先 guji db push，或加 --force 丢掉本地改动")
    tmp = ws_dir / ".central-pull.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    for _ in range(3):
        r0 = src.status()
        stats = materialize(src, ws, tmp, ("workspace.yaml",) + PREFIXES, cache=cache, bucket=bucket)
        if src.status() == r0 or not src.changes_since(ws, r0, limit=1):
            break
    else:
        raise SystemExit("读的过程中一直有新写入，稍后再拉")
    got = {p.relative_to(tmp).as_posix() for p in tmp.rglob("*") if p.is_file()}
    removed = 0
    for rel, p in list(_walk(ws_dir)):
        if rel not in got and classify(rel) != "patch":
            p.unlink()
            removed += 1
    for rel in sorted(got):
        dst = ws_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp / rel, dst)
    shutil.rmtree(tmp, ignore_errors=True)
    write_meta(ws_dir, ws=ws, branch=getattr(src, "branch", "main"), rev=r0)
    return {"ws": ws, "rev": r0, "written": len(got), "removed": removed, **{k: v for k, v in stats.items() if k != "ws"}}


def local_changes(src, ws_dir: Path, ws: str, missing: bool = True) -> list[str]:
    """本地与库里 sha 不同、多出或（``missing`` 时）少了的文件（不比刻例图：图跟着实例行走）。
    没 pull --full 过的目录不算「少了」：那是还没拉，不是删了。"""
    db = {r["src_path"]: r["sha256"] for r in src.rows("source_files", ws)}
    local = {}
    for rel, p in _walk(ws_dir):
        if classify(rel) != "patch":
            local[rel] = sha256(p.read_bytes())
    keys = (set(db) | set(local)) if missing else set(local)
    return sorted(k for k in keys if db.get(k) != local.get(k))


def push_dir(conn, ws_dir: Path, *, actor: str | None, dry_run: bool = False,
             allow_delete: bool = False, uploader=None) -> dict:
    """把工作区写回中心库（直连 Postgres；云会话经 wsbridge）。``uploader(images)`` 传图。"""
    from .importer import import_scans
    ws_dir = Path(ws_dir)
    meta = read_meta(ws_dir)
    if not meta:
        raise SystemExit("工作区没有 .central.json：先 guji db pull -w <工作区> --full")
    base = int(meta["rev"])
    sc = scan_dir(ws_dir)
    if sc.ws != meta.get("ws"):
        raise SystemExit(f".central.json 记的工作区是 {meta.get('ws')}，这里是 {sc.ws}")
    local_paths = {r.src_path for r in sc.rows}

    def guard(cur):
        cur.execute("SELECT 1 FROM changes WHERE ws = %s AND rev > %s LIMIT 1", (sc.ws, base))
        if cur.fetchone():
            raise StaleBase(f"工作区 {sc.ws} 在 rev {base} 之后已有别人写入；先 guji db pull --full 再改再 push")
        cur.execute("SELECT src_path FROM source_files WHERE ws = %s", (sc.ws,))
        gone = sorted({r[0] for r in cur.fetchall()} - local_paths)
        if gone and not allow_delete:
            raise FileDeleteRefused(f"本地少了 {len(gone)} 个库里有的文件（如 {gone[:3]}），"
                                    f"多半是没 pull 全；确认要删再加 --allow-delete")

    # 图：先传（只增不改，写库失败也无害）
    images: dict[str, Path] = {}
    patch_dir = ws_dir / "output" / "glyph_store" / "patches"
    for r in sc.rows:
        if r.tbl == "glyph_instances" and r.cols.get("patch_sha"):
            images[r.cols["patch_sha"]] = patch_dir / f"{r.key[0].replace(':', '_')}.png"
        elif r.tbl == "anchor_patches_meta":
            images[r.cols["sha256"]] = ws_dir / r.src_path
    lost = sorted(str(p) for p in images.values() if not p.exists())
    if lost:
        raise SystemExit(f"实例引用的 {len(lost)} 张图本地没有（如 {lost[:3]}）")
    up = None
    if not dry_run and uploader is not None:
        up = uploader(images)
    rep = import_scans(conn, [sc], label=f"push:{sc.ws}@{base}", actor=actor, dry_run=dry_run,
                       source="push", guard=guard, allow_delete=allow_delete)
    out = rep.as_dict()
    out["base_rev"] = base
    out["images"] = up
    if not dry_run:
        write_meta(ws_dir, ws=sc.ws, branch=meta.get("branch", "main"), rev=rep.rev_to)
    return out
