"""工作区的中心库数据副本（GUJI-608 写入切换之后）：数据不在工作区里，在工作区外的数据目录。

    guji db migrate -w <工作区>   # 一次性：工作区里的数据核对后挪进数据目录，工作区里删掉
    guji db pull    -w <工作区>   # 中心库 → 数据目录（只在本地没有未推改动时）
    guji db push    -w <工作区>   # 数据目录 → 中心库（先比版本号）

**布局**：工作区根只留 ``workspace.yaml``（身份）与标记 ``.central.json``（{ws, branch}）；
册 yaml、人裁、台账、批次、人工配置、字形库在 ``core.workspace.central_data_dir``
（``$GUJI_DATA_HOME/<分支>/<工作区 id>/``，布局同旧工作区），``core.workspace`` 的路径函数
见到标记就指过去。原图、products、cache、glyph.db 照旧在工作区。

**版本**：数据目录里的 ``.central-state.json`` 记拉取时的 rev、每个文件的基准 sha（``base``）和
当时 glyph.db 的指纹。``local_changes`` 不连网，对的是基准：改了、新增、删掉都算。
push 拿库锁后查这个工作区在 rev 之后有没有别人写过，有就整次拒绝（``StaleBase``）；
只追加的台账少了行、整个文件丢了也拒绝。

**glyph.db**：人裁消费者改的是 glyph.db，要导出成字形库账本才进得了库。push、pull 前看 glyph.db
指纹与上次记的是否相同，不同就先导出。pull 拉到新的字形库账本才重建 glyph.db；迁移不碰它
（重建会让库指纹变、各书产物判过期）。导出、重建、指纹由调用方（``cli_db``）传进来，本层不 import 聚类。
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..core.workspace import CENTRAL_MARKER, central_data_dir, central_marker
from .scope import GS, TABLES, classify, sha256

SCOPE = ("books/", "feedback/", "review/", "config/", GS)
STATE = ".central-state.json"
WS_YAML = "workspace.yaml"


class StaleBase(RuntimeError):
    pass


class FileDeleteRefused(RuntimeError):
    pass


@dataclass
class GlyphHooks:
    """glyph.db 相关的三件事（由 cli_db 用聚类层实现）。"""
    fingerprint: Callable[[Path], str]                 # (db_path) -> 指纹；库不存在返回 ""
    export: Callable[[Path, Path], dict]               # (db_path, store_dir) -> 统计
    rebuild: Callable[[Path, Path, Path], dict]        # (ws_dir, store_dir, db_path) -> 统计
    db_path: Path


# ---- 布局 ----

def data_dir(ws_dir: Path) -> Path:
    m = central_marker(Path(ws_dir))
    if not m:
        raise SystemExit(f"{ws_dir} 还没迁到中心库（没有 {CENTRAL_MARKER}）：先 guji db migrate -w {ws_dir}")
    return central_data_dir(str(m["ws"]), str(m.get("branch") or "main"))


def _walk(root: Path, patches: bool = True):
    """root 下归中心库管的文件（不含 workspace.yaml）：(相对路径, 绝对路径)。"""
    root = Path(root)
    for pre in SCOPE:
        d = root / pre.rstrip("/")
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file():
                rel = p.relative_to(root).as_posix()
                kind = classify(rel)
                if kind is not None and (patches or kind != "patch"):
                    yield rel, p


def manifest(ws_dir: Path, data: Path) -> dict[str, str]:
    """{相对路径: sha}：数据目录里的文件（刻例图除外，图跟着实例行走）＋工作区的 workspace.yaml。"""
    out = {rel: sha256(p.read_bytes()) for rel, p in _walk(data, patches=False)}
    y = Path(ws_dir) / WS_YAML
    if y.exists():
        out[WS_YAML] = sha256(y.read_bytes())
    return out


def scan(ws_dir: Path, data: Path):
    from .scope import scan_files
    items = [(WS_YAML, (lambda: (Path(ws_dir) / WS_YAML).read_bytes()))]
    items += [(rel, (lambda p=p: p.read_bytes())) for rel, p in _walk(data)]
    return scan_files(items, Path(ws_dir).name)


def read_state(data: Path) -> dict | None:
    p = Path(data) / STATE
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def write_state(data: Path, **kw) -> None:
    kw["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    p = Path(data) / STATE
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(kw, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _diff(base: dict[str, str], cur: dict[str, str]) -> list[str]:
    return sorted(k for k in set(base) | set(cur) if base.get(k) != cur.get(k))


def _export_if_changed(glyph: GlyphHooks | None, data: Path, state: dict | None) -> bool:
    """glyph.db 自上次记录后变过就导出进数据目录的字形库。返回是否导出了。"""
    if glyph is None or not Path(glyph.db_path).exists():
        return False
    fp = glyph.fingerprint(glyph.db_path)
    if state is not None and fp == state.get("glyph_db_fp"):
        return False
    glyph.export(glyph.db_path, data / GS.rstrip("/"))
    return True


def local_changes(ws_dir: Path, glyph: GlyphHooks | None = None) -> list[str]:
    """相对上次拉取／推送的基准，本地改了的文件（glyph.db 有未导出的改动会先导出）。"""
    data = data_dir(ws_dir)
    st = read_state(data)
    if st is None:
        raise SystemExit(f"数据目录 {data} 没有 {STATE}：先 guji db pull -w {ws_dir}")
    _export_if_changed(glyph, data, st)
    return _diff(st["base"], manifest(ws_dir, data))


def _db_manifest(src, ws: str) -> dict[str, str]:
    """库里这个工作区的文件 {相对路径: sha}：文本在 source_files，锚图在 anchor_patches_meta。"""
    out = {r["src_path"]: r["sha256"] for r in src.rows("source_files", ws)}
    out.update({r["src_path"]: r["sha256"] for r in src.rows("anchor_patches_meta", ws)})
    return out


def _materialize(src, ws: str, tmp: Path, cache, bucket: str, retries: int = 3) -> tuple[int, dict]:
    from .materialize import materialize
    for _ in range(retries):
        r0 = src.status()
        stats = materialize(src, ws, tmp, (WS_YAML,) + SCOPE, cache=cache, bucket=bucket)
        if src.status() == r0 or not src.changes_since(ws, r0, limit=1):
            return r0, stats
    raise SystemExit("读的过程中工作区一直有新写入，稍后再拉")


def _install(tmp: Path, ws_dir: Path, data: Path) -> tuple[int, int]:
    """把 tmp 里还原的文件换进数据目录（镜像；没被引用的刻例图留着），workspace.yaml 进工作区。"""
    got = {p.relative_to(tmp).as_posix() for p in tmp.rglob("*") if p.is_file()}
    removed = 0
    for rel, p in list(_walk(data)):
        if rel not in got and classify(rel) != "patch":
            p.unlink()
            removed += 1
    for rel in sorted(got):
        dst = (Path(ws_dir) if rel == WS_YAML else data) / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp / rel, dst)
    shutil.rmtree(tmp, ignore_errors=True)
    return len(got), removed


def pull(src, ws_dir: Path, *, cache=None, bucket: str = "main", force: bool = False,
         glyph: GlyphHooks | None = None) -> dict:
    """中心库 → 数据目录。本地有未推的改动就拒绝（``force`` 丢掉）。"""
    ws_dir = Path(ws_dir)
    m = central_marker(ws_dir) or {}
    data = data_dir(ws_dir)
    ws = str(m["ws"])
    data.mkdir(parents=True, exist_ok=True)
    st = read_state(data)
    if st is not None and not force:
        dirty = local_changes(ws_dir, glyph)
        if dirty:
            raise SystemExit(f"本地有 {len(dirty)} 个文件改了还没推（如 {dirty[:3]}）；"
                             f"先 guji db push，或加 --force 丢掉本地改动")
    old_base = (st or {}).get("base", {})
    tmp = data.parent / f".{data.name}.pull.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    rev, stats = _materialize(src, ws, tmp, cache, bucket)
    written, removed = _install(tmp, ws_dir, data)
    base = _db_manifest(src, ws)
    store_changed = any(old_base.get(k) != base.get(k) for k in set(old_base) | set(base) if k.startswith(GS))
    out = {"ws": ws, "rev": rev, "data_dir": str(data), "written": written, "removed": removed,
           **{k: v for k, v in stats.items() if k != "ws"}}
    fp = (st or {}).get("glyph_db_fp")
    if glyph is not None and (store_changed or not Path(glyph.db_path).exists() or force):
        out["glyph_db"] = glyph.rebuild(ws_dir, data / GS.rstrip("/"), glyph.db_path)
        fp = glyph.fingerprint(glyph.db_path)
    write_state(data, ws=ws, branch=str(m.get("branch") or "main"), rev=rev, base=base, glyph_db_fp=fp)
    return out


def push(conn, ws_dir: Path, *, actor: str | None, dry_run: bool = False, allow_delete: bool = False,
         uploader=None, glyph: GlyphHooks | None = None) -> dict:
    """数据目录 → 中心库（直连 Postgres；云会话经 wsbridge）。``uploader(images)`` 传新图。"""
    from .importer import import_scans
    ws_dir = Path(ws_dir)
    data = data_dir(ws_dir)
    st = read_state(data)
    if st is None:
        raise SystemExit(f"数据目录 {data} 没有 {STATE}：先 guji db pull -w {ws_dir}")
    base = int(st["rev"])
    exported = _export_if_changed(glyph, data, st)
    sc = scan(ws_dir, data)
    if sc.ws != st.get("ws"):
        raise SystemExit(f"数据目录记的工作区是 {st.get('ws')}，workspace.yaml 写的是 {sc.ws}")
    local_paths = {r.src_path for r in sc.rows}

    def guard(cur):
        cur.execute("SELECT 1 FROM changes WHERE ws = %s AND rev > %s LIMIT 1", (sc.ws, base))
        if cur.fetchone():
            raise StaleBase(f"工作区 {sc.ws} 在 rev {base} 之后已有别人写入；先 guji db pull 再推")
        cur.execute("SELECT src_path FROM source_files WHERE ws = %s", (sc.ws,))
        gone = sorted({r[0] for r in cur.fetchall()} - local_paths)
        if gone and not allow_delete:
            raise FileDeleteRefused(f"本地少了 {len(gone)} 个库里有的文件（如 {gone[:3]}）；"
                                    f"确认要删再加 --allow-delete")

    images: dict[str, Path] = {}
    patch_dir = data / GS / "patches"
    for r in sc.rows:
        if r.tbl == "glyph_instances" and r.cols.get("patch_sha"):
            images[r.cols["patch_sha"]] = patch_dir / f"{r.key[0].replace(':', '_')}.png"
        elif r.tbl == "anchor_patches_meta":
            images[r.cols["sha256"]] = data / r.src_path
    lost = sorted(str(p) for p in images.values() if not p.exists())
    if lost:
        raise SystemExit(f"实例引用的 {len(lost)} 张图本地没有（如 {lost[:3]}）")
    up = uploader(images) if (uploader is not None and not dry_run) else None
    rep = import_scans(conn, [sc], label=f"push:{sc.ws}@{base}", actor=actor, dry_run=dry_run,
                       source="push", guard=guard, allow_delete=allow_delete)
    out = rep.as_dict()
    out.update(base_rev=base, images=up, glyph_exported=exported, data_dir=str(data))
    if not dry_run:
        fp = glyph.fingerprint(glyph.db_path) if glyph is not None and Path(glyph.db_path).exists() else st.get("glyph_db_fp")
        write_state(data, ws=sc.ws, branch=st.get("branch", "main"), rev=rep.rev_to,
                    base=manifest(ws_dir, data), glyph_db_fp=fp)
    return out


def migrate(src, ws_dir: Path, *, cache=None, bucket: str = "main", keep_local: bool = False,
            dry_run: bool = False, glyph: GlyphHooks | None = None) -> dict:
    """一次性：工作区里的数据核对后挪进数据目录，工作区里删掉，写标记。

    工作区里的文件与库里不一致就停下列出来（多半是检出旧了，或有没进库的改动）；确认本地的才对，
    加 ``keep_local``：数据目录先按库还原，再用工作区里的这些文件盖上去，成为待推改动。
    glyph.db 不动（它是本地派生物，重建会让库指纹变）。"""
    from .pull import workspace_id
    ws_dir = Path(ws_dir)
    if central_marker(ws_dir):
        raise SystemExit(f"{ws_dir} 已经迁过（有 {CENTRAL_MARKER}）；要更新用 guji db pull")
    ws = workspace_id(ws_dir)
    branch = getattr(src, "branch", "main")
    db = _db_manifest(src, ws)
    if not db:
        raise SystemExit(f"中心库里没有工作区 {ws}（分支 {branch}）")
    local = {rel: sha256(p.read_bytes()) for rel, p in _walk(ws_dir, patches=False)}
    differ = sorted(rel for rel in local if db.get(rel) != local[rel])
    report = {"ws": ws, "branch": branch, "data_dir": str(central_data_dir(ws, branch)),
              "local_files": len(local), "db_files": len(db), "differ": differ[:50], "n_differ": len(differ),
              "dry_run": dry_run}
    if differ and not keep_local:
        raise SystemExit(f"工作区里有 {len(differ)} 个文件与中心库不一致（如 {differ[:5]}）：检出旧了就先 git pull，"
                         f"确认本地的才对就加 --keep-local（迁完它们是待推改动，再 guji db push）")
    if dry_run:
        return report
    data = central_data_dir(ws, branch)
    data.mkdir(parents=True, exist_ok=True)
    tmp = data.parent / f".{data.name}.pull.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    rev, stats = _materialize(src, ws, tmp, cache, bucket)
    (tmp / WS_YAML).unlink(missing_ok=True)            # 工作区自己的 workspace.yaml 不动
    written, _ = _install(tmp, ws_dir, data)
    fp = glyph.fingerprint(glyph.db_path) if glyph is not None and Path(glyph.db_path).exists() else None
    write_state(data, ws=ws, branch=branch, rev=rev, base=_db_manifest(src, ws), glyph_db_fp=fp)
    for rel in differ:
        dst = data / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ws_dir / rel, dst)
    (ws_dir / CENTRAL_MARKER).write_text(json.dumps({"ws": ws, "branch": branch}, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
    removed = 0
    for rel, p in list(_walk(ws_dir)):
        p.unlink()
        removed += 1
    for pre in SCOPE:                                  # 删空目录（备份等不归库管的文件留着）
        d = ws_dir / pre.rstrip("/")
        if d.is_dir():
            for sub in sorted((x for x in d.rglob("*") if x.is_dir()), key=lambda x: -len(x.parts)):
                if not any(sub.iterdir()):
                    sub.rmdir()
            if not any(d.iterdir()):
                d.rmdir()
    report.update(rev=rev, written=written, removed_from_workspace=removed, pending=len(differ),
                  **{k: v for k, v in stats.items() if k != "ws"})
    return report


# ---- 同步：拉库里的新改动、与本地改动合并、再推（GUJI-608 B 块）----

class SyncConflict(RuntimeError):
    pass


APPEND_ONLY = {t for t, spec in TABLES.items() if spec.append_only}


def _merge_append(local: bytes, remote: bytes) -> bytes | None:
    """两边都只在共同前缀后面追加了行 → 前缀＋库里的新行＋本地的新行（本地与库里相同的行不重复）。

    不知道基准内容，共同前缀就当基准：若有一边其实改了前缀里的行，合出来的文件会少那一边的旧行，
    推的时候只追加台账少行会被导入器拒掉（``DeleteRefused``），不会悄悄丢数据。"""
    lo, re_ = local.decode("utf-8").splitlines(), remote.decode("utf-8").splitlines()
    n = 0
    while n < min(len(lo), len(re_)) and lo[n] == re_[n]:
        n += 1
    tail_r = re_[n:]
    seen = set(tail_r)
    tail_l = [x for x in lo[n:] if x not in seen]
    merged = lo[:n] + tail_r + tail_l
    return ("\n".join(merged) + "\n").encode("utf-8") if merged else b""


def sync(src, conn, ws_dir: Path, *, actor: str | None, cache=None, bucket: str = "main",
         uploader=None, glyph: GlyphHooks | None = None, dry_run: bool = False) -> dict:
    """拉 → 合并 → 推，一步做完（控制台写完、定时任务都用它）。

    库里在基准 rev 之后没人写过：直接推。有人写过：库里改了、本地没改的文件取库里的；本地改了、库里没改的
    留本地的；两边都改了的只追加台账（events、consumed、anchors）按「共同前缀＋库里新行＋本地新行」合，
    别的文件两边都改了就整次停下（``SyncConflict``），什么都不动。"""
    ws_dir = Path(ws_dir)
    data = data_dir(ws_dir)
    st = read_state(data)
    if st is None:
        raise SystemExit(f"数据目录 {data} 没有 {STATE}：先 guji db pull -w {ws_dir}")
    ws = str(st["ws"])
    exported = _export_if_changed(glyph, data, st)
    base = st["base"]
    local = manifest(ws_dir, data)
    mine = set(_diff(base, local))
    out: dict = {"ws": ws, "local_changes": sorted(mine), "glyph_exported": exported}
    if not src.changes_since(ws, int(st["rev"]), limit=1):
        if not mine:
            return {**out, "action": "nothing"}
        return {**out, "action": "push", "push": push(conn, ws_dir, actor=actor, dry_run=dry_run,
                                                       uploader=uploader, glyph=glyph)}
    # 库里有新改动：拉到旁边，逐文件合
    tmp = data.parent / f".{data.name}.sync.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    rev, _ = _materialize(src, ws, tmp, cache, bucket)
    remote = _db_manifest(src, ws)
    theirs = set(_diff(base, remote))
    both = sorted(mine & theirs)
    merged: dict[str, bytes] = {}
    conflicts = []
    for rel in both:
        lp = (ws_dir if rel == WS_YAML else data) / rel
        rp = tmp / rel
        if local.get(rel) == remote.get(rel):
            continue                                       # 两边改成一样
        if classify(rel) in APPEND_ONLY and lp.exists() and rp.exists():
            m = _merge_append(lp.read_bytes(), rp.read_bytes())
            if m is not None:
                merged[rel] = m
                continue
        conflicts.append(rel)
    if conflicts:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SyncConflict(f"这些文件本地和库里都改了，合不了（如 {conflicts[:5]}）；"
                           f"要库里的：guji db pull --force；要本地的：手工合进去再推")
    out.update(remote_changes=sorted(theirs), merged=sorted(merged), rev_remote=rev)
    if dry_run:
        shutil.rmtree(tmp, ignore_errors=True)
        return {**out, "action": "merge (dry-run)"}
    # 库里改了、本地没改的 → 用库里的；本地删了而库里没动的保持删除
    store_changed = False
    for rel in sorted(theirs - mine):
        dst = (ws_dir if rel == WS_YAML else data) / rel
        if (tmp / rel).exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp / rel, dst)
        elif dst.exists():
            dst.unlink()
        store_changed |= rel.startswith(GS)
    patches = tmp / GS / "patches"                         # 库里新实例的刻例图
    if patches.is_dir():
        for p in patches.iterdir():
            q = data / GS / "patches" / p.name
            if not q.exists():
                q.parent.mkdir(parents=True, exist_ok=True)
                os.replace(p, q)
    for rel, b in merged.items():
        (data / rel).write_bytes(b)
    shutil.rmtree(tmp, ignore_errors=True)
    fp = st.get("glyph_db_fp")
    if glyph is not None and store_changed and Path(glyph.db_path).exists():
        out["glyph_db"] = glyph.rebuild(ws_dir, data / GS.rstrip("/"), glyph.db_path)
        fp = glyph.fingerprint(glyph.db_path)
    write_state(data, ws=ws, branch=st.get("branch", "main"), rev=rev, base=remote, glyph_db_fp=fp)
    if not _diff(remote, manifest(ws_dir, data)):
        return {**out, "action": "pulled"}
    return {**out, "action": "merged+push", "push": push(conn, ws_dir, actor=actor, uploader=uploader, glyph=glyph)}
