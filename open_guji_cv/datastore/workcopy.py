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
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..core.workspace import (
    _CENTRAL_NAME,
    CENTRAL_MARKER,
    borrowed_root,
    central_data_dir,
    central_marker,
    resolve_borrow,
)
from .scope import BLOB_TABLES, GS, TABLES, classify, sha256

SCOPE = ("books/", "feedback/", "review/", "config/", "corpus/", GS)
STATE = ".central-state.json"
WS_YAML = "workspace.yaml"
BORROW_STATE = ".borrowed-state.json"

#: 共享层的只读工作区（共享方案 3.2 节）：普通 push／sync 一律拒绝，只有升级脚本能写；
#: ``glyphlib-*`` 每版一个工作区，只能写新开的版本（sheldon 10-19：升级时脚本可写）
SHARED_PREFIX = "glyphlib-"
SHARED_NAMES = frozenset({"corpus-base"})


def is_shared_ws(ws: str) -> bool:
    return ws.startswith(SHARED_PREFIX) or ws in SHARED_NAMES


class StaleBase(RuntimeError):
    pass


class FileDeleteRefused(RuntimeError):
    pass


@dataclass
class GlyphHooks:
    """glyph.db 相关的三件事（由 cli_db 用聚类层实现）。"""
    fingerprint: Callable[[Path], str]                 # (db_path) -> 指纹；库不存在返回 ""
    export: Callable[[Path, Path], dict]               # (db_path, store_dir) -> 统计
    rebuild: Callable[..., dict]                       # (ws_dir, store_dir, db_path, extras) -> 统计；extras＝借来的字形库
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
    """库里这个工作区的文件 {相对路径: sha}：文本在 source_files，锚图、整理本在 BLOB_TABLES。"""
    from .materialize import _rows, blob_rows
    out = {r["src_path"]: r["sha256"] for r in _rows(src, "source_files", ws, ("src_path", "sha256"))}
    for tbl in BLOB_TABLES:
        out.update({r["src_path"]: r["sha256"] for r in blob_rows(src, tbl, ws)})
    return out


def _local(ws_dir: Path, data: Path):
    """``materialize`` 的 ``reuse``：相对路径 → 本机现有文件（workspace.yaml 在工作区，别的在数据目录）。"""
    def f(rel: str) -> Path | None:
        p = (Path(ws_dir) if rel == WS_YAML else Path(data)) / rel
        return p if p.is_file() else None
    return f


# ---- 工作区快照（Neon 免费档按公网流量计；新机器整拉殿本走 Neon 约 50 MB，快照包约 6–7 MB 走 R2 不收费）----

SNAPSHOT_ENV = "GUJI_DATA_SNAPSHOT"      # 设 0 关掉快照（不下也不传）
SNAPSHOT_SKIP_EXT = (".png",)            # 图另有 R2 缓存，不进快照


def _snapshots_on(src) -> bool:
    return os.environ.get(SNAPSHOT_ENV, "1") != "0" and hasattr(src, "get_snapshot")


def _seed_from_snapshot(src, ws: str, seed: Path) -> int | None:
    """把最新快照解到 ``seed``（只收普通文件、相对路径、不许 ..）。返回快照 rev；没有返回 None。出错只当没有。"""
    import io
    import sys
    import tarfile
    try:
        got = src.get_snapshot(ws)
        if not got:
            return None
        rev, blob = got
        if seed.exists():
            shutil.rmtree(seed)
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
            for m in tf.getmembers():
                name = m.name
                if not m.isfile() or name.startswith("/") or ".." in Path(name).parts:
                    continue
                f = tf.extractfile(m)
                if f is None:
                    continue
                out = seed / name
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(f.read())
        return int(rev)
    except Exception as e:                       # 快照只是缓存：坏了、断了都退回整拉
        print(f"[db] 快照不可用，改从库里整拉：{e}", file=sys.stderr)
        shutil.rmtree(seed, ignore_errors=True)
        return None


def _publish_snapshot(src, ws: str, rev: int, ws_dir: Path, data: Path, base: dict[str, str]) -> int | None:
    """把本机已与库一致的文本文件打成 tar.gz 存上去。只放 sha 与 ``base`` 一致的；令牌不能写就算了。返回字节数。"""
    import io
    import sys
    import tarfile
    if not hasattr(src, "put_snapshot"):
        return None
    if _read_only(src):
        # 读令牌存不上（403），先问一句，省得白打一个包（殿本约 9 s；云端新机器拉库都是读令牌）
        print("[db] 读令牌不存快照（不影响本次拉取）", file=sys.stderr)
        return None
    local = _local(ws_dir, data)
    buf = io.BytesIO()
    try:
        with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=9) as tf:
            for rel in sorted(base):
                if rel.endswith(SNAPSHOT_SKIP_EXT):
                    continue
                p = local(rel)
                if p is None:
                    continue
                b = p.read_bytes()
                if sha256(b) != base[rel]:
                    continue
                ti = tarfile.TarInfo(rel)
                ti.size = len(b)
                tf.addfile(ti, io.BytesIO(b))
        src.put_snapshot(ws, rev, buf.getvalue())
        return len(buf.getvalue())
    except Exception as e:                       # 读令牌、旧 Worker、网络问题：不影响拉取
        print(f"[db] 快照没存上（不影响本次拉取）：{e}", file=sys.stderr)
        return None


def _read_only(src) -> bool:
    """令牌是不是只读（``whoami`` 的 ``role == "read"``）；问不到当可写，照旧去试。"""
    try:
        return hasattr(src, "whoami") and (src.whoami() or {}).get("role") == "read"
    except Exception:                            # noqa: BLE001 —— 旧 Worker、网络问题：照旧试着存
        return False


def _materialize(src, ws: str, tmp: Path, cache, bucket: str, retries: int = 3,
                 prefixes: tuple[str, ...] = (WS_YAML,) + SCOPE, reuse=None) -> tuple[int, dict]:
    from .materialize import MaterializeError, materialize
    for _ in range(retries):
        r0 = src.status()
        try:
            stats = materialize(src, ws, tmp, prefixes, cache=cache, bucket=bucket, reuse=reuse)
        except MaterializeError:
            # 先读 source_files、后读行：中间有人推了新行（如 admissions.jsonl 追加），行数对不上会报
            # 「超出 n_lines」或 sha 不符。读的过程中工作区有新写入就重读，否则是真不一致，照抛（10-23 A30 sync 撞上）
            if src.status() == r0 or not src.changes_since(ws, r0, limit=1):
                raise
            continue
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


# ---- 借库（共享方案 S4）----

def borrow_entries(ws_dir: Path) -> list[str]:
    """``workspace.yaml`` 的 ``glyph_lib.borrow``（没配返回空表）。"""
    import yaml
    y = Path(ws_dir) / WS_YAML
    cfg = (yaml.safe_load(y.read_text(encoding="utf-8")) or {}) if y.exists() else {}
    return [str(x) for x in ((cfg.get("glyph_lib") or {}).get("borrow") or [])]


def readonly_copy(src, name: str, branch: str, prefixes: tuple[str, ...], *, cache=None,
                  bucket: str = "main") -> tuple[int, bool]:
    """把中心库工作区 ``name`` 里 ``prefixes`` 下的文件拉成本机只读副本（``core.workspace.borrowed_root``）。

    副本旁 ``.borrowed-state.json`` 记拉到的 rev；库里那个工作区没新写入、要的目录都在就不重拉。
    返回 (rev, 这次是否重拉了)。借字形库（S4）和底库清单（S2）共用。"""
    root = borrowed_root(name, branch)
    stf = root / BORROW_STATE
    st = json.loads(stf.read_text(encoding="utf-8")) if stf.exists() else None
    have = st is not None and list(st.get("prefixes") or [GS]) == list(prefixes) \
        and all((root / p.rstrip("/")).exists() for p in prefixes)
    if have and not src.changes_since(name, int(st["rev"]), limit=1):
        return int(st["rev"]), False
    tmp = root.parent / f".{name}.borrow.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    rev, _ = _materialize(src, name, tmp, cache, bucket, prefixes=prefixes,
                          reuse=(lambda rel: (root / rel) if (root / rel).is_file() else None) if root.exists() else None)
    (tmp / BORROW_STATE).write_text(json.dumps({"ws": name, "branch": branch, "rev": rev,
                                                "prefixes": list(prefixes)}) + "\n", encoding="utf-8")
    if root.exists():
        shutil.rmtree(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp, root)
    return rev, True


def borrow_stores(src, ws_dir: Path, *, cache=None, bucket: str = "main") -> tuple[list[Path], list[str]]:
    """借来的字形库 → (目录列表, 签名)。签名变了才要重建 glyph.db。

    写中心库工作区名的条目：拉那个工作区的 ``output/glyph_store/`` 到 ``core.workspace.borrowed_root``
    （只读副本，见 ``readonly_copy``）。写路径的条目照旧当本地目录。"""
    ws_dir = Path(ws_dir)
    m = central_marker(ws_dir) or {}
    own, branch = str(m.get("ws") or ""), str(m.get("branch") or "main")
    dirs: list[Path] = []
    sig: list[str] = []
    for e in borrow_entries(ws_dir):
        d = resolve_borrow(e, ws_dir)
        if m and _CENTRAL_NAME.match(e) and not (ws_dir / e).exists():
            if e == own:
                raise SystemExit(f"workspace.yaml 的 glyph_lib.borrow 写了自己（{e}）")
            rev, _ = readonly_copy(src, e, branch, (GS,), cache=cache, bucket=bucket)
            sig.append(f"{e}@{rev}")
        else:
            if not d.is_dir():
                raise SystemExit(f"借库 {e} 不存在（{d}）；迁到中心库的工作区请写被借工作区的名字")
            sig.append(f"path:{d}")
        dirs.append(d)
    return dirs, sig


def uses_corpus_base(ws_dir: Path) -> bool:
    """这个工作区的书库清单有没有写 ``base:``（两级清单，共享方案 S2）。"""
    from ..core.corpus_pin import BASE_WS, manifest_path, versions
    ws_dir = Path(ws_dir)
    if (central_marker(ws_dir) or {}).get("ws") == BASE_WS:
        return False
    for v in versions(ws_dir):
        try:
            if json.loads(manifest_path(ws_dir, v).read_text(encoding="utf-8")).get("base") is not None:
                return True
        except (OSError, ValueError):
            continue
    return False


def refresh_corpus_base(src, ws_dir: Path, *, cache=None, bucket: str = "main", always: bool = False) -> int | None:
    """书库清单用到底库（或 ``always``）时，把 ``corpus-base`` 的底库清单拉成只读副本。返回 rev；用不到返回 None。"""
    from ..core.corpus_pin import BASE_DIR, BASE_WS
    from .materialize import MaterializeError
    m = central_marker(Path(ws_dir)) or {}
    if not m or m.get("ws") == BASE_WS or not (always or uses_corpus_base(ws_dir)):
        return None
    try:
        rev, _ = readonly_copy(src, BASE_WS, str(m.get("branch") or "main"), (BASE_DIR + "/",),
                               cache=cache, bucket=bucket)
    except MaterializeError as e:
        raise SystemExit(f"中心库里还没有底库清单（{BASE_WS}）：先 guji corpus build-base（{e}）") from e
    return rev


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
    reuse = _local(ws_dir, data)
    seed = data.parent / f".{data.name}.seed"
    seed_rev = _seed_from_snapshot(src, ws, seed) if st is None and _snapshots_on(src) else None
    if seed_rev is not None:                     # 新机器：先用快照里的文件，库里只要之后变了的
        here = reuse
        reuse = lambda rel: here(rel) or ((seed / rel) if (seed / rel).is_file() else None)  # noqa: E731
    try:
        rev, stats = _materialize(src, ws, tmp, cache, bucket, reuse=reuse)
    finally:
        shutil.rmtree(seed, ignore_errors=True)
    written, removed = _install(tmp, ws_dir, data)
    base = _db_manifest(src, ws)
    store_changed = any(old_base.get(k) != base.get(k) for k in set(old_base) | set(base) if k.startswith(GS))
    out = {"ws": ws, "rev": rev, "data_dir": str(data), "written": written, "removed": removed,
           **{k: v for k, v in stats.items() if k != "ws"}}
    cb = refresh_corpus_base(src, ws_dir, cache=cache, bucket=bucket)
    if cb is not None:
        out["corpus_base"] = cb
    fp = (st or {}).get("glyph_db_fp")
    bsig = (st or {}).get("borrow", [])
    if glyph is not None:
        extras, bsig = borrow_stores(src, ws_dir, cache=cache, bucket=bucket)
        if extras:
            out["borrow"] = bsig
        if store_changed or not Path(glyph.db_path).exists() or force or bsig != (st or {}).get("borrow", []):
            out["glyph_db"] = glyph.rebuild(ws_dir, data / GS.rstrip("/"), glyph.db_path, extras)
            fp = glyph.fingerprint(glyph.db_path)
    write_state(data, ws=ws, branch=str(m.get("branch") or "main"), rev=rev, base=base, glyph_db_fp=fp,
                borrow=bsig)
    if seed_rev is not None:
        out["snapshot_rev"] = seed_rev
    if stats.get("fetched") and _snapshots_on(src):   # 这次向库要过文件：存一份新快照给下一台新机器
        out["snapshot_bytes"] = _publish_snapshot(src, ws, rev, ws_dir, data, base)
    return out


#: 字形库快照清单（GUJI-727，``core/glyph_pin.py``）：``config/glyph-pack/g<N>/manifest.json``
GLYPH_PACK_DIR = "config/glyph-pack/"
_GLYPH_PACK_MAN = re.compile(r"^config/glyph-pack/g\d+/manifest\.json$")


def glyph_pack_blobs(ws_dir: Path, data: Path, base: dict[str, str], rows) -> dict[str, Path]:
    """这次 push 新带上的字形库快照清单（基准里没有的）→ 它登记的文本条目 ``{sha: 本机文件}``，随 push 传 R2。

    刻例图不用管：出快照要求数据目录已推干净，图早已按 sha 进桶；借来的库是从中心库拉的，图也在桶里。
    本机文件已与清单不同的拒推：那一版的文本谁都拼不出来了，删掉这个号重出快照。"""
    out: dict[str, Path] = {}
    for r in rows:
        if r.tbl != "files" or not _GLYPH_PACK_MAN.match(r.src_path) or r.src_path in base:
            continue
        man = json.loads((data / r.src_path).read_text(encoding="utf-8"))
        bad = []
        for it in man.get("items", []):
            if it.get("type") != "txt":
                continue
            root = str(it["root"])
            if root == "gs":
                p = data / GS / it["path"]
            elif root.startswith("borrow:"):
                p = resolve_borrow(root[len("borrow:"):], ws_dir) / it["path"]
            else:
                bad.append(f"{root}:{it['path']}")
                continue
            if p.is_file() and sha256(p.read_bytes()) == it["sha256"]:
                out[it["sha256"]] = p
            else:
                bad.append(f"{root}:{it['path']}")
        if bad:
            raise SystemExit(f"字形库快照 {r.src_path} 登记的 {len(bad)} 个文本本机已经变了（如 {bad[:3]}），"
                             f"推上去也没人拼得出这一版；删掉这个号、guji glyph-db snapshot 重出")
    return out


def push(conn, ws_dir: Path, *, actor: str | None, dry_run: bool = False, allow_delete: bool = False,
         uploader=None, glyph: GlyphHooks | None = None, shared_writer: bool = False) -> dict:
    """数据目录 → 中心库（直连 Postgres；云会话经 wsbridge）。``uploader(images[, ext=])`` 传新图与整理本。

    共享层的只读工作区（``is_shared_ws``）只有升级脚本能写（``shared_writer=True``），``glyphlib-*`` 还只能写一次。"""
    from .importer import import_scans
    ws_dir = Path(ws_dir)
    data = data_dir(ws_dir)
    st = read_state(data)
    creating = st is None and shared_writer and is_shared_ws(str((central_marker(ws_dir) or {}).get("ws") or ""))
    if creating:                                       # 升级脚本开新的共享层工作区（库里还没有它）
        m = central_marker(ws_dir) or {}
        st = {"ws": str(m["ws"]), "branch": str(m.get("branch") or "main"), "rev": 0, "base": {}}
    if st is None:
        raise SystemExit(f"数据目录 {data} 没有 {STATE}：先 guji db pull -w {ws_dir}")
    base = int(st["rev"])
    exported = _export_if_changed(glyph, data, st)
    sc = scan(ws_dir, data)
    if sc.ws != st.get("ws"):
        raise SystemExit(f"数据目录记的工作区是 {st.get('ws')}，workspace.yaml 写的是 {sc.ws}")
    local_paths = {r.src_path for r in sc.rows}
    # 换图源（GUJI-748 §六）：切过图源的册（册 yaml 有 source_rev），锚里页表 rev 不符的**新**事件拒收
    from ..core.event_files import RevGate
    rgate = RevGate(books_dir=data / "books")
    stale_ev = {r.key[1]: r.src_path for r in sc.rows
                if r.tbl == "events" and not rgate.admits(r.cols.get("kind"), r.cols.get("target") or {})}
    if not creating and not shared_writer:
        from ..core.corpus_pin import push_problems
        problems = push_problems(ws_dir)
        if problems:
            raise SystemExit(problems[0])
    if is_shared_ws(sc.ws) and not shared_writer:
        raise SystemExit(f"{sc.ws} 是共享层的只读工作区（共享方案 3.2 节），普通 push／sync 不能写；"
                         f"由升级脚本出新版本")

    def guard(cur):
        if creating:
            cur.execute("SELECT 1 FROM changes WHERE ws = %s LIMIT 1", (sc.ws,))
            if cur.fetchone():
                raise StaleBase(f"中心库里已经有 {sc.ws}；先 guji db pull 再写")
        if shared_writer and sc.ws.startswith(SHARED_PREFIX):
            cur.execute("SELECT 1 FROM changes WHERE ws = %s LIMIT 1", (sc.ws,))
            if cur.fetchone():
                raise SystemExit(f"{sc.ws} 已经发布过，版本不可改；出新版本请开新的工作区")
        cur.execute("SELECT 1 FROM changes WHERE ws = %s AND rev > %s LIMIT 1", (sc.ws, base))
        if cur.fetchone():
            raise StaleBase(f"工作区 {sc.ws} 在 rev {base} 之后已有别人写入；先 guji db pull 再推")
        if stale_ev:                                           # 库里已有的旧事件照留，只拦这次新推的
            cur.execute("SELECT id FROM events WHERE ws = %s AND id = ANY(%s)", (sc.ws, list(stale_ev)))
            new = sorted(set(stale_ev) - {r[0] for r in cur.fetchall()})
            if new:
                raise SystemExit(f"{len(new)} 条新事件指向已换图源的册，锚里页表 rev 与册 yaml 的 source_rev 不符，"
                                 f"中心库拒收（{rgate.note()}）。如 {new[:3]}（{stale_ev[new[0]]}）。"
                                 f"旧页号的裁决请用 `guji cellvotes migrate` 按格级对照表迁移后再推，"
                                 f"或从本地事件文件里删掉这几条")
        if not creating and not shared_writer:                 # 已发布的语料库、字形库版本不可改（用户 10-20；GUJI-727）
            cur.execute("SELECT src_path, sha256 FROM files WHERE ws = %s "
                        "AND (src_path LIKE 'config/corpus-pack/v%%/manifest.json' "
                        "OR src_path LIKE 'config/glyph-pack/g%%/manifest.json')", (sc.ws,))
            db_sha = dict(cur.fetchall())
            changed = sorted(r.src_path for r in sc.rows if r.tbl == "files" and r.src_path in db_sha
                             and r.cols.get("sha256", db_sha[r.src_path]) != db_sha[r.src_path])
            if changed:
                what = "字形库" if changed[0].startswith(GLYPH_PACK_DIR) else "语料库"
                raise SystemExit(f"{what}清单 {changed[:3]} 已发布，版本不可改；出新版本"
                                 f"（{'guji glyph-db snapshot' if what == '字形库' else 'guji corpus build'}）")
        cur.execute("SELECT src_path FROM source_files WHERE ws = %s"
                    + "".join(f" UNION ALL SELECT src_path FROM {t} WHERE ws = %s" for t in BLOB_TABLES),
                    (sc.ws,) * (1 + len(BLOB_TABLES)))
        gone = sorted({r[0] for r in cur.fetchall()} - local_paths)   # 锚图也算：v0.4.0 及更早 pull 不还原锚图
        if gone and not allow_delete:
            raise FileDeleteRefused(f"本地少了 {len(gone)} 个库里有的文件（如 {gone[:3]}）；"
                                    f"确认要删再加 --allow-delete")

    # 要进 R2 的文件，按 R2 键后缀分组：刻例图、锚图是 png，整理本是 txt（scope.BLOB_TABLES）
    images: dict[str, dict[str, Path]] = {}
    patch_dir = data / GS / "patches"
    for r in sc.rows:
        if r.tbl == "glyph_instances" and r.cols.get("patch_sha"):
            images.setdefault("png", {})[r.cols["patch_sha"]] = patch_dir / f"{r.key[0].replace(':', '_')}.png"
        elif r.tbl in BLOB_TABLES:
            images.setdefault(BLOB_TABLES[r.tbl], {})[r.cols["sha256"]] = data / r.src_path
    lost = sorted(str(p) for g in images.values() for p in g.values() if not p.exists())
    if lost:
        raise SystemExit(f"实例引用的 {len(lost)} 张图本地没有（如 {lost[:3]}）")
    pack_txt = glyph_pack_blobs(ws_dir, data, st.get("base", {}), sc.rows)
    if pack_txt:                                       # 新出的字形库快照：登记的文本随这次 push 进 R2
        images.setdefault("txt", {}).update(pack_txt)
    if images and uploader is not None and not dry_run:
        # 库里已有的图（导入或之前推过时已进桶）不再逐张签名核对：每次推都核两万张要十几分钟，
        # 连接闲置被断，事务一开就死（10-19 D 推 vol01 裁决两次失败）
        known: dict[str, set[str]] = {}
        with conn.cursor() as cur:
            cur.execute("SELECT patch_sha FROM glyph_instances WHERE ws = %s AND patch_sha IS NOT NULL",
                        (sc.ws,))
            known["png"] = {r[0] for r in cur.fetchall()}
            for t, ext in BLOB_TABLES.items():
                cur.execute("SELECT to_regclass(%s)", (t,))
                if cur.fetchone()[0] is None:          # 新表还没建（导入时 apply_schema 才建）
                    continue
                cur.execute(f"SELECT sha256 FROM {t} WHERE ws = %s", (sc.ws,))
                known.setdefault(ext, set()).update(r[0] for r in cur.fetchall())
        conn.commit()
        images = {ext: {sha: p for sha, p in g.items() if sha not in known.get(ext, ())}
                  for ext, g in images.items()}
        images = {ext: g for ext, g in images.items() if g}
    up = None
    if uploader is not None and not dry_run and images:
        res = {ext: (uploader(g) if ext == "png" else uploader(g, ext=ext))   # 只收图的 uploader 照旧能用
               for ext, g in sorted(images.items())}
        up = res["png"] if list(res) == ["png"] else res
    rep = import_scans(conn, [sc], label=f"push:{sc.ws}@{base}", actor=actor, dry_run=dry_run,
                       source="push", guard=guard, allow_delete=allow_delete)
    out = rep.as_dict()
    out.update(base_rev=base, images=up, glyph_exported=exported, data_dir=str(data))
    if not dry_run:
        fp = glyph.fingerprint(glyph.db_path) if glyph is not None and Path(glyph.db_path).exists() else st.get("glyph_db_fp")
        write_state(data, ws=sc.ws, branch=st.get("branch", "main"), rev=rep.rev_to,
                    base=manifest(ws_dir, data), glyph_db_fp=fp, borrow=st.get("borrow", []))
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
        rep = adopt(ws_dir, dry_run=dry_run)
        if rep is None:
            raise SystemExit(f"{ws_dir} 已经迁过（有 {CENTRAL_MARKER}）；要更新用 guji db pull")
        return rep
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
    adopted = adopt(ws_dir)                            # 工作区根的 corpus-pack/ 挪进数据目录 config/
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
    report.update(rev=rev, written=written, removed_from_workspace=removed,
                  pending=len(differ) + (adopted or {}).get("adopt", 0),
                  **{k: v for k, v in stats.items() if k != "ws"})
    return report


#: 收录范围后来才扩进来的工作区根目录 → 数据目录里的落点（2026-10-19 共享方案 2.2 节：整理本、语料库清单）
ADOPT = {"corpus": "corpus", "corpus-pack": "config/corpus-pack"}


def adopt(ws_dir: Path, *, dry_run: bool = False) -> dict | None:
    """补迁：已迁过的工作区，根上还留着后来才纳入中心库的目录（``ADOPT``），挪进数据目录成为待推改动。

    数据目录里已有同路径同内容的文件直接删掉工作区里的；内容不同就整次停下，什么都不动。
    没有可补迁的返回 None。挪完要 ``guji db push``（或 sync）才进库。"""
    ws_dir = Path(ws_dir)
    data = data_dir(ws_dir)
    moves: list[tuple[Path, Path, str]] = []
    for src_name, dst_rel in ADOPT.items():
        root = ws_dir / src_name
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            rel = f"{dst_rel}/{p.relative_to(root).as_posix()}"
            if classify(rel) is None:
                continue
            moves.append((p, data / rel, rel))
    if not moves:
        return None
    clash = [rel for p, q, rel in moves if q.exists() and sha256(q.read_bytes()) != sha256(p.read_bytes())]
    if clash:
        raise SystemExit(f"补迁：数据目录里已有 {len(clash)} 个同路径但内容不同的文件（如 {clash[:3]}）；"
                         f"先弄清哪份对，再手工处理")
    same = sum(1 for _, q, _ in moves if q.exists())
    report = {"ws_dir": str(ws_dir), "data_dir": str(data), "adopt": len(moves) - same, "already": same,
              "files": [rel for *_, rel in moves][:50], "dry_run": dry_run}
    if dry_run:
        return report
    for p, q, _ in moves:
        if q.exists():
            p.unlink()
        else:
            q.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), q)
    for src_name in ADOPT:                              # 删空目录（不归库管的文件留着）
        d = ws_dir / src_name
        if d.is_dir():
            for sub in sorted((x for x in d.rglob("*") if x.is_dir()), key=lambda x: -len(x.parts)):
                if not any(sub.iterdir()):
                    sub.rmdir()
            if not any(d.iterdir()):
                d.rmdir()
    report["next"] = f"guji db push -w {ws_dir}"
    return report


# ---- 同步：拉库里的新改动、与本地改动合并、再推（GUJI-608 B 块）----

class SyncConflict(RuntimeError):
    pass


APPEND_ONLY = {t for t, spec in TABLES.items() if spec.append_only}


def _split_append(local: bytes, remote: bytes) -> tuple[list[str], list[str], list[str]]:
    """共同前缀、库里在前缀后的新行、本地在前缀后的新行（与库里相同的行不重复）。"""
    lo, re_ = local.decode("utf-8").splitlines(), remote.decode("utf-8").splitlines()
    n = 0
    while n < min(len(lo), len(re_)) and lo[n] == re_[n]:
        n += 1
    tail_r = re_[n:]
    seen = set(tail_r)
    return lo[:n], tail_r, [x for x in lo[n:] if x not in seen]


def _join(lines: list[str]) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""


def _merge_append(local: bytes, remote: bytes) -> bytes | None:
    """两边都只在共同前缀后面追加了行 → 前缀＋库里的新行＋本地的新行（本地与库里相同的行不重复）。

    不知道基准内容，共同前缀就当基准：若有一边其实改了前缀里的行，合出来的文件会少那一边的旧行，
    推的时候只追加台账少行会被导入器拒掉（``DeleteRefused``），不会悄悄丢数据。"""
    head, tail_r, tail_l = _split_append(local, remote)
    return _join(head + tail_r + tail_l)


def _merge_events(local: bytes, remote: bytes) -> tuple[bytes, dict[str, str]]:
    """人裁事件文件的合并（规范 §9 F-6）：同 ``_merge_append``，再给本地新行里与库里撞号的重新编号。

    两台机器往同一批次追加时各自从同一个 ``seq`` 往后编，合出来同一 ``id`` 两行内容不同：记账互相遮挡、
    库主键 ``(ws, src_path, id)`` 冲突。库里的行已经推出去了、别的机器可能已消费，所以只动本地的：
    顺延到该批次合并后的下一个空 ``seq``，与 ``EventLog.append`` 撞号顺延同一语义。
    返回（合并后的字节，旧 id → 新 id）。"""
    head, tail_r, tail_l = _split_append(local, remote)
    rows = [json.loads(x) for x in head + tail_r if x.strip()]
    taken = {r.get("id") for r in rows}
    top: dict[str, int] = {}
    for r in rows:
        if isinstance(r.get("seq"), int):
            top[r.get("batch")] = max(top.get(r.get("batch"), 0), r["seq"])
    renamed: dict[str, str] = {}
    out_l = []
    for x in tail_l:
        if not x.strip():
            continue
        d = json.loads(x)
        b = d.get("batch")
        if d.get("id") in taken and isinstance(d.get("seq"), int):
            s = top.get(b, 0) + 1
            new = f"evt_{b}_{s:06d}"
            renamed[d["id"]] = new
            d["id"], d["seq"] = new, s
            x = json.dumps(d, ensure_ascii=False, sort_keys=True)
        if isinstance(d.get("seq"), int):
            top[b] = max(top.get(b, 0), d["seq"])
        taken.add(d.get("id"))
        out_l.append(x)
    return _join(head + tail_r + out_l), renamed


def _rename_ids(text: str, renamed: dict[str, str]) -> str:
    for old, new in renamed.items():
        text = text.replace(f'"{old}"', f'"{new}"')
    return text


def _apply_renames(renamed: dict[str, str], *, merged: dict[str, bytes], local_only: dict[str, Path],
                   remote: dict[str, bytes]) -> list[str]:
    """本地事件改了 id → 本地写的记账、补锚、金标里引用它的地方跟着改（只改本地新写的行）。

    ``merged``：两边都改了的只追加台账，按库里的字节切出本地新行再改；``local_only``：只有本地改了的文件，
    基准之后的新 id 只可能是本地写的，整文件改。"""
    if not renamed:
        return []
    touched = []
    for rel, b in list(merged.items()):
        if classify(rel) == "events" or rel not in remote:
            continue
        head, tail_r, tail_l = _split_append(b, remote[rel])
        nl = [_rename_ids(x, renamed) for x in tail_l]
        if nl != tail_l:
            merged[rel] = _join(head + tail_r + nl)
            touched.append(rel)
    for rel, path in local_only.items():
        if classify(rel) == "events" or not path.exists() or path.suffix not in (".jsonl", ".json"):
            continue
        t = path.read_text(encoding="utf-8")
        nt = _rename_ids(t, renamed)
        if nt != t:
            path.write_text(nt, encoding="utf-8")
            touched.append(rel)
    return sorted(touched)


def _event_ids(b: bytes) -> set[str]:
    out = set()
    for x in b.decode("utf-8").splitlines():
        if x.strip():
            try:
                out.add(json.loads(x).get("id"))
            except ValueError:
                continue
    return out - {None}


def _local_new_event_ids(data: Path, tmp: Path, merged: dict[str, bytes], mine: set[str]) -> set[str]:
    """本地有、库里没有的人裁事件 id（合并后的本地文件对库里那份）。"""
    ids: set[str] = set()
    for rel in sorted(mine):
        if classify(rel) != "events":
            continue
        b = merged.get(rel)
        if b is None:
            p = data / rel
            if not p.exists():
                continue
            b = p.read_bytes()
        r = tmp / rel
        ids |= _event_ids(b) - (_event_ids(r.read_bytes()) if r.exists() else set())
    return ids


def _drop_glyph_consumed(data: Path, ids: set[str]) -> int:
    """字形库消费者（``consumed/glyph*.jsonl``）里这些事件的记账删掉，好让它们在库里的字形库上重新消费。返回删的行数。"""
    n = 0
    for f in sorted((data / "feedback" / "consumed").glob("glyph*.jsonl")):
        lines = f.read_text(encoding="utf-8").splitlines()
        keep = []
        for x in lines:
            try:
                drop = bool(x.strip()) and json.loads(x).get("event") in ids
            except ValueError:
                drop = False
            n += drop
            if not drop:
                keep.append(x)
        if len(keep) != len(lines):
            f.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    return n


def sync(src, conn, ws_dir: Path, *, actor: str | None, cache=None, bucket: str = "main",
         uploader=None, glyph: GlyphHooks | None = None, dry_run: bool = False,
         replay: Callable[[set[str]], dict] | None = None) -> dict:
    """拉 → 合并 → 推，一步做完（控制台写完、定时任务都用它）。

    库里在基准 rev 之后没人写过：直接推。有人写过：库里改了、本地没改的文件取库里的；本地改了、库里没改的
    留本地的；两边都改了的只追加台账（events、consumed、anchors）按「共同前缀＋库里新行＋本地新行」合，
    别的文件两边都改了就整次停下（``SyncConflict``），什么都不动。

    字形库（``output/glyph_store/``）两边都改了、又给了 ``replay`` 时不停：字形库是消费者从人裁事件算出来的，
    本地那份改动就是本地新事件过消费者的结果。取库里的字形库、重建 glyph.db，删掉这些事件在字形库消费者
    （``consumed/glyph*.jsonl``）里的记账，再用 ``replay(新事件 id)`` 让它们在库里的字形库上重新消费一遍，
    然后照常推（册 005 10-23 两次手工 ``pull --force`` 重写重推，就是这一步）。"""
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
    if glyph is not None and borrow_entries(ws_dir):    # 借来的库有新版：只重建 glyph.db，不算本地改动
        extras, bsig = borrow_stores(src, ws_dir, cache=cache, bucket=bucket)
        if bsig != st.get("borrow", []) and not dry_run and Path(glyph.db_path).exists():
            out["glyph_db"] = glyph.rebuild(ws_dir, data / GS.rstrip("/"), glyph.db_path, extras)
            st = {**st, "borrow": bsig, "glyph_db_fp": glyph.fingerprint(glyph.db_path)}
            write_state(data, **{k: v for k, v in st.items() if k != "at"})
            out["borrow"] = bsig
    if not dry_run:                                    # 底库清单有新版：只更新只读副本
        cb = refresh_corpus_base(src, ws_dir, cache=cache, bucket=bucket)
        if cb is not None:
            out["corpus_base"] = cb
    if not src.changes_since(ws, int(st["rev"]), limit=1):
        if not mine:
            return {**out, "action": "nothing"}
        return {**out, "action": "push", "push": push(conn, ws_dir, actor=actor, dry_run=dry_run,
                                                       uploader=uploader, glyph=glyph)}
    # 库里有新改动：拉到旁边，逐文件合
    tmp = data.parent / f".{data.name}.sync.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    rev, _ = _materialize(src, ws, tmp, cache, bucket, reuse=_local(ws_dir, data))
    remote = _db_manifest(src, ws)
    theirs = set(_diff(base, remote))
    both = sorted(mine & theirs)
    merged: dict[str, bytes] = {}
    renamed: dict[str, str] = {}
    conflicts = []
    glyph_taken: list[str] = []
    for rel in both:
        lp = (ws_dir if rel == WS_YAML else data) / rel
        rp = tmp / rel
        if local.get(rel) == remote.get(rel):
            continue                                       # 两边改成一样
        if classify(rel) == "events" and lp.exists() and rp.exists():
            merged[rel], ren = _merge_events(lp.read_bytes(), rp.read_bytes())
            renamed.update(ren)
            continue
        if classify(rel) in APPEND_ONLY and lp.exists() and rp.exists():
            m = _merge_append(lp.read_bytes(), rp.read_bytes())
            if m is not None:
                merged[rel] = m
                continue
        if replay is not None and glyph is not None and rel.startswith(GS) and rp.exists():
            merged[rel] = rp.read_bytes()                  # 字形库取库里的，本地新事件之后重新消费
            glyph_taken.append(rel)
            continue
        conflicts.append(rel)
    replay_ids: set[str] = set()
    if glyph_taken:
        replay_ids = _local_new_event_ids(data, tmp, merged, mine)
        if not replay_ids:                                 # 本地字形库改了却没有新事件：不是消费者算的，不敢丢
            conflicts += glyph_taken
            glyph_taken = []
        else:                                              # 本地只改了的字形库文件也回到库里那份，免得同一事件算两遍
            for rel in sorted(mine - theirs):
                if rel.startswith(GS) and not rel.startswith(GS + "patches/"):
                    merged[rel] = (tmp / rel).read_bytes() if (tmp / rel).exists() else None
                    glyph_taken.append(rel)
    if conflicts:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SyncConflict(f"这些文件本地和库里都改了，合不了（如 {conflicts[:5]}）；"
                           f"要库里的：guji db pull --force；要本地的：手工合进去再推")
    out.update(remote_changes=sorted(theirs), merged=sorted(merged), rev_remote=rev)
    if glyph_taken:
        out["glyph_taken_remote"] = glyph_taken
    if renamed:
        out["renumbered"] = renamed
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
    if renamed:                                            # 撞号重编：本地引用跟着改（规范 §9 F-6）
        out["renamed_refs"] = _apply_renames(
            renamed, merged=merged, remote={r: (tmp / r).read_bytes() for r in merged if (tmp / r).exists()},
            local_only={r: data / r for r in sorted(mine - theirs) if r != WS_YAML})
    for rel, b in merged.items():
        if b is None:
            (data / rel).unlink(missing_ok=True)
        else:
            (data / rel).write_bytes(b)
    shutil.rmtree(tmp, ignore_errors=True)
    if glyph_taken:
        store_changed = True
        out["replay_unconsumed"] = _drop_glyph_consumed(data, replay_ids)
    fp = st.get("glyph_db_fp")
    if glyph is not None and store_changed and Path(glyph.db_path).exists():
        extras, _ = borrow_stores(src, ws_dir, cache=cache, bucket=bucket)
        out["glyph_db"] = glyph.rebuild(ws_dir, data / GS.rstrip("/"), glyph.db_path, extras)
        fp = glyph.fingerprint(glyph.db_path)
    write_state(data, ws=ws, branch=st.get("branch", "main"), rev=rev, base=remote, glyph_db_fp=fp,
                borrow=st.get("borrow", []))
    if replay_ids:
        out["replay"] = replay(replay_ids)
        _export_if_changed(glyph, data, read_state(data))  # 重新消费写的是 glyph.db，导出成字形库再比对、推
    if not _diff(remote, manifest(ws_dir, data)):
        if _snapshots_on(src):
            out["snapshot_bytes"] = _publish_snapshot(src, ws, rev, ws_dir, data, remote)
        return {**out, "action": "pulled"}
    return {**out, "action": "merged+push", "push": push(conn, ws_dir, actor=actor, uploader=uploader, glyph=glyph)}
