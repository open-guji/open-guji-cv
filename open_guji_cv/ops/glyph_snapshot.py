"""字形库快照 g<N>：出号、按版本建库、传 R2（GUJI-727，设计见 `doc/design/字形库按版本钉-细设计.md`）。

- `snapshot`（`guji glyph-db snapshot`）：把本书字形库真源 `output/glyph_store/` 与借来的字形库逐文件登记成
  `config/glyph-pack/g<N>/manifest.json`（只出到本机，推中心库走 `guji db push`）。数据目录有没推的改动就拒绝，
  所以快照就是中心库 `rev` 那一刻的字形库；内容与最新一版相同拒绝（不空升）。出号时顺手建好 `glyph-g<N>.db`。
- `build_pinned_db`（`guji glyph-db pin-build`）：按清单拼出那一版的真源（本机同 sha 的文件优先，缺的从 R2 按 sha 取），
  `rebuild_from_store` 建库，字体域从当前 `glyph.db` 原样拷，`meta` 记 `{n, digest, build}`。digest 与建库代码都没变就复用。
- `upload_blobs`（`guji glyph-db snapshot-upload`）：清单里的文本与图按 sha 传 R2（已有跳过）；缺省演练。
- `verify_remote`（`guji glyph-db pin-verify`）：不用本机文件，只从 R2 取，核对每个条目都取得到、sha 对得上。

本模块不在任何 Step 的 `code_deps` 里，改它不让各册过期。钉号怎么进参数见 `core/glyph_pin.py`。
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
from pathlib import Path

from ..core.glyph_pin import (BORROW_ROOT, META_KEY, OWN_ROOT, items_digest, load_manifest, manifest_path,
                              pinned_db_meta, pinned_db_path, versions)

#: 建库这一路上的模块：任一改了，从同一份真源建出来的库就可能不同（派生表示），要重建
BUILD_MODULES = ("open_guji_cv.clustering.glyph_db", "open_guji_cv.clustering.canonical",
                 "open_guji_cv.clustering.normalize", "open_guji_cv.clustering.features")


class _ws:
    """临时把 ``core.workspace`` 的工作区换成 ``ws``（路径函数都跟着走）。"""

    def __init__(self, ws: Path):
        self.ws = Path(ws)

    def __enter__(self):
        from ..core.workspace import set_workspace_override
        self.tok = set_workspace_override(str(self.ws))
        return self.ws

    def __exit__(self, *exc):
        from ..core.workspace import reset_workspace_override
        reset_workspace_override(self.tok)


def build_key() -> dict:
    from ..clustering.glyph_db import ALGO_VERSIONS
    from ..core.engine import code_hash_of_module
    return {"code": {m.rsplit(".", 1)[1]: code_hash_of_module(m) for m in BUILD_MODULES},
            "algo": dict(ALGO_VERSIONS)}


def _sha256(p: Path) -> str:
    from ..products.store import sha256_file
    return sha256_file(p)


_SHA: dict[tuple[str, int, int], str] = {}


def _sha_cached(p: Path) -> str:
    st = p.stat()
    k = (str(p), st.st_size, st.st_mtime_ns)
    if k not in _SHA:
        _SHA[k] = _sha256(p)
    return _SHA[k]


def _store_dir(ws: Path) -> Path:
    with _ws(ws):
        from ..core.workspace import glyph_store_path
        return Path(glyph_store_path())


def _borrows(ws: Path) -> list[tuple[str, Path]]:
    """借来的字形库：[(名字, 本机目录)]。名字取法同 `glyph_match._borrow_name`（`borrow_fingerprint` 认它）。"""
    from ..core.workspace import resolve_borrow
    from ..datastore.workcopy import borrow_entries
    from ..steps.glyph_match import _borrow_name
    out = []
    for e in borrow_entries(ws):
        d = resolve_borrow(e, ws)
        if not d.is_dir():
            raise SystemExit(f"借库 {e} 本机没有（{d}）；先 guji db pull -w {ws}")
        out.append((_borrow_name(str(d)), d))
    return out


def _walk(root: Path, label: str) -> list[dict]:
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out.append({"root": label, "path": p.relative_to(root).as_posix(), "sha256": _sha_cached(p),
                        "size": p.stat().st_size, "type": "png" if p.suffix.lower() == ".png" else "txt"})
    return out


def collect(ws: Path) -> tuple[list[dict], list[str]]:
    """本机当前字形库真源与借库 → (清单条目, 借库名)。"""
    store = _store_dir(ws)
    if not store.is_dir():
        raise SystemExit(f"没有字形库真源 {store}")
    items = _walk(store, OWN_ROOT)
    names = []
    for name, d in _borrows(ws):
        items += _walk(d, BORROW_ROOT + name)
        names.append(name)
    return sorted(items, key=lambda i: (i["root"], i["path"])), names


def _local_sources(ws: Path) -> dict[str, Path]:
    """清单条目的根 → 本机目录（用来找同 sha 的现成文件）。"""
    out = {OWN_ROOT: _store_dir(ws)}
    try:
        for name, d in _borrows(ws):
            out[BORROW_ROOT + name] = d
    except SystemExit:
        pass
    return out


def _dest_dir(tmp: Path, root: str) -> Path:
    """拼目录里条目的位置：本书在 ``own/output/glyph_store``；借库在 ``.borrowed/<名>/output/glyph_store``
    （借库名从路径倒数第三级取，`borrow_fingerprint` 才与现行重建的库一致）。"""
    if root == OWN_ROOT:
        return tmp / "own" / "output" / "glyph_store"
    return tmp / ".borrowed" / root[len(BORROW_ROOT):] / "output" / "glyph_store"


def assemble(ws: Path, man: dict, dest: Path, *, local: bool = True, src=None, cache=None) -> dict:
    """按清单拼出那一版的真源到 ``dest``。本机同 sha 的文件优先（``local=False`` 不用），缺的从 R2 按 sha 取。
    有条目取不到或 sha 不符就报错，不留半个目录。"""
    from ..datastore.client import BlobCache
    if dest.exists():
        shutil.rmtree(dest)
    srcs = _local_sources(ws) if local else {}
    todo: dict[str, list[dict]] = {"txt": [], "png": []}
    placed_local = 0
    for it in man["items"]:
        out = _dest_dir(dest, it["root"]) / it["path"]
        out.parent.mkdir(parents=True, exist_ok=True)
        base = srcs.get(it["root"])
        p = base / it["path"] if base is not None else None
        if p is not None and p.is_file() and _sha_cached(p) == it["sha256"]:
            shutil.copyfile(p, out)
            placed_local += 1
        else:
            todo[it.get("type", "txt")].append(it)
    fetched, missing = 0, []
    if todo["txt"] or todo["png"]:
        cache = cache or BlobCache()
        need = [it for its in todo.values() for it in its if not cache.has(it["sha256"])]
        if need and src is None:                          # 本机缓存里都有就不连网
            from ..datastore.client import WorkerSource
            src = WorkerSource()
        for ext, its in todo.items():
            if not its:
                continue
            got = cache.ensure(src, [it["sha256"] for it in its], ext=ext)
            missing += got.get("missing", [])
            for it in its:
                if cache.has(it["sha256"]):
                    shutil.copyfile(cache.path(it["sha256"]), _dest_dir(dest, it["root"]) / it["path"])
                    fetched += 1
    if missing:
        shutil.rmtree(dest, ignore_errors=True)
        raise SystemExit(f"g{man['n']} 有 {len(missing)} 个条目本机没有、R2 也取不到（如 {missing[:3]}）；"
                         f"出快照的机器先跑 guji glyph-db snapshot-upload --pin {man['n']} --execute")
    return {"local": placed_local, "fetched": fetched}


def _copy_fonts(live_db: Path, db) -> list[dict]:
    """当前库的字体域原样拷进新库（`font_pack` 的导出／导入，逐列相同）。当前库没有字体域就不拷。"""
    import sqlite3
    import tempfile
    from ..clustering.font_pack import export_pack, import_pack
    from ..clustering.glyph_db import GlyphDB
    if not Path(live_db).exists():
        return []
    with sqlite3.connect(f"file:{live_db}?mode=ro", uri=True) as c:
        eds = [r[0] for r in c.execute("SELECT source_id FROM sources WHERE kind='font' ORDER BY source_id")]
    out = []
    if not eds:
        return out
    live = GlyphDB(live_db)
    try:
        with tempfile.TemporaryDirectory() as td:
            for ed in eds:
                f = Path(td) / f"{ed}.sqlite"
                export_pack(live, ed, f)
                out.append(import_pack(db, f, ed))
                f.unlink(missing_ok=True)
    finally:
        live.close()
    return out


def _fonts_fp(live_db: Path) -> str:
    """当前库字体域的指纹（只看 `font_manifests`）；没有库或没导字体 → 空串。"""
    if not Path(live_db).exists():
        return ""
    from ..clustering.glyph_fp import font_domain_fingerprint
    return font_domain_fingerprint(live_db) or ""


def build_pinned_db(ws: Path, version: int, *, force: bool = False, local: bool = True, src=None) -> dict:
    """建 ``glyph-g<N>.db``。库在、digest、建库代码、当前库的字体域都对得上就复用（``force`` 重建）。
    字体域也要对：新机器常是先拉库建好钉版库、后导字体，导完下次用时要重建一次把字体域带上。

    同一工作区同一个号**排队建**（2026-10-24）：殿本 vol09、vol10 同一秒起跑，两个 `guji pipeline` 各自
    `ensure_pins` 建 g2，拼真源用的是同一个临时目录 `cache/glyph-pin/g2`，后来的一方开头 `rmtree` 掉前一方
    拼了一半的目录，前一方于是只读到实例、没读到 glyphs/exemplars，建出 instances 20,661、exemplars 0 的库，
    两册 Step5-a 起全部无效。现在按号加文件锁，拿到锁后再判一次复用（另一方刚建好就直接用）。"""
    import fcntl
    with _ws(ws):
        lock_path = pinned_db_path(version).with_name(f".glyph-g{int(version)}.build.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            return _build_pinned_db_locked(ws, version, force=force, local=local, src=src)
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def _build_pinned_db_locked(ws: Path, version: int, *, force: bool = False, local: bool = True, src=None) -> dict:
    from ..clustering.glyph_db import GlyphDB, rebuild_from_store
    ws = Path(ws)
    man = load_manifest(ws, version)
    if man is None:
        raise SystemExit(f"没有字形库 g{version} 的清单：{manifest_path(ws, version)}（先 guji db pull，或 guji glyph-db snapshot）")
    key = build_key()
    with _ws(ws):
        db_path = pinned_db_path(version)
        from ..core.workspace import cache_root, glyph_db_path
        live_db, tmp = Path(glyph_db_path()), Path(cache_root()) / "glyph-pin" / f"g{version}"
    fonts_fp = _fonts_fp(live_db)
    meta = pinned_db_meta(db_path)
    if (not force and meta and meta.get("digest") == man["digest"] and meta.get("build") == key
            and meta.get("fonts") == fonts_fp):
        return {"pin": version, "db": str(db_path), "reused": True}
    info = assemble(ws, man, tmp, local=local, src=src)
    own = _dest_dir(tmp, OWN_ROOT)
    extras = sorted(p for p in (tmp / ".borrowed").glob("*/output/glyph_store")) if (tmp / ".borrowed").is_dir() else []
    part = db_path.with_name(f".{db_path.name}.tmp{os.getpid()}")
    part.unlink(missing_ok=True)
    jobs = os.cpu_count() or 1
    summary = (rebuild_from_store(own, part, extra_stores=extras, jobs=jobs) if extras
               else rebuild_from_store(own, part, jobs=jobs))
    db = GlyphDB(part)
    try:
        fonts = _copy_fonts(live_db, db)
        db.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                        (META_KEY, json.dumps({"n": version, "digest": man["digest"], "build": key,
                                               "fonts": fonts_fp}, ensure_ascii=False, sort_keys=True)))
        db.conn.commit()
    finally:
        db.close()
    from ..clustering.glyph_db import assert_db_not_silently_empty
    try:
        # 建完先自检再换上：空刻例的库（10-24 vol09/10）别落成 glyph-g<N>.db 让跑批读到
        assert_db_not_silently_empty(part, store_dir=own)
    except RuntimeError:
        part.unlink(missing_ok=True)
        raise
    with _ws(ws):
        fps = _fingerprints(part)
    db = GlyphDB(part)
    try:       # 清单里没记 fingerprints 的（--no-build 出的）靠这份；`core/glyph_pin._snapshot_pin` 读
        row = db.conn.execute("SELECT value FROM meta WHERE key=?", (META_KEY,)).fetchone()
        m = json.loads(row[0])
        m["fingerprints"] = fps
        db.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                        (META_KEY, json.dumps(m, ensure_ascii=False, sort_keys=True)))
        db.conn.commit()
    finally:
        db.close()
    os.replace(part, db_path)
    shutil.rmtree(tmp, ignore_errors=True)
    return {"pin": version, "db": str(db_path), "reused": False, **info, "fonts": fonts,
            "rebuild": {k: v for k, v in summary.items() if isinstance(v, (int, str))}}


def _fingerprints(db_path: Path) -> dict:
    """新建的钉版库里，参数要用到、又不能不开库算的那几项（`core/glyph_pin._snapshot_pin` 读）。"""
    import sqlite3
    from ..steps.glyph_match import borrow_fingerprint
    from ..steps.seed_admit import _approx_fingerprint
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as c:
        n_human = c.execute("SELECT count(*) FROM admissions WHERE provenance='human'").fetchone()[0]
        n_inst = c.execute("SELECT count(*) FROM instances i JOIN sources s USING(source_id) "
                           "WHERE s.kind != 'font'").fetchone()[0]
    return {"borrow_fingerprint": borrow_fingerprint(db_path), "approx": bool(_approx_fingerprint(str(db_path))),
            "n_human": int(n_human), "n_instances": int(n_inst)}


def _dump(man: dict) -> str:
    """清单写法：头部字段缩进，条目一行一个（殿本约 1.85 万条，随 ``config/`` 进 ``files`` 表约 2 MB）。"""
    head = {k: v for k, v in man.items() if k != "items"}
    body = ",\n".join(" " + json.dumps(i, ensure_ascii=False, sort_keys=True) for i in man["items"])
    return json.dumps(head, ensure_ascii=False, indent=1)[:-2] + ',\n "items": [\n' + body + "\n ]\n}\n"


def snapshot(ws: Path, *, note: str = "", require_clean: bool = True, build: bool = True) -> dict:
    """出新号 g<N>（N = 已有最大号 + 1）。只写本机：清单在数据目录，推中心库走 ``guji db push``。"""
    from ..core.workspace import central_marker
    ws = Path(ws)
    m = central_marker(ws)
    rev = None
    if m:
        from ..datastore.workcopy import data_dir, local_changes, read_state
        from .central_glyph import glyph_hooks
        if require_clean:
            dirty = local_changes(ws, glyph_hooks(ws))
            if dirty:
                raise SystemExit(f"数据目录有 {len(dirty)} 个文件没推（如 {dirty[:3]}）；先 guji db sync，"
                                 f"快照要与中心库的某个 rev 对得上")
        rev = (read_state(data_dir(ws)) or {}).get("rev")
    items, borrow = collect(ws)
    digest = items_digest(items)
    have = versions(ws)
    if have:
        last = load_manifest(ws, have[-1])
        if last and last["digest"] == digest:
            raise SystemExit(f"字形库与 g{have[-1]} 内容相同（{digest}），不空升")
    n = (have[-1] if have else 0) + 1
    man = {"version": 1, "n": n, "ws": str((m or {}).get("ws") or ws.name), "rev": rev,
           "created": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "note": note, "digest": digest, "borrow": borrow, "build": build_key(), "items": items}
    _keep_local(ws, items)
    mp = manifest_path(ws, n)
    mp.parent.mkdir(parents=True, exist_ok=True)
    part = mp.with_name(".manifest.json.tmp")
    part.write_text(_dump(man), encoding="utf-8")
    os.replace(part, mp)
    out = {"pin": n, "digest": digest, "rev": rev, "items": len(items),
           "txt": sum(1 for i in items if i["type"] == "txt"), "png": sum(1 for i in items if i["type"] == "png"),
           "borrow": borrow, "manifest": str(mp)}
    if build:
        try:
            out["db"] = build_pinned_db(ws, n, force=True)
            with _ws(ws):
                man["fingerprints"] = _fingerprints(pinned_db_path(n))
        except BaseException:
            mp.unlink(missing_ok=True)                  # 建不出库的快照不算数
            raise
        mp.write_text(_dump(man), encoding="utf-8")
        out["fingerprints"] = man["fingerprints"]
    return out


def _keep_local(ws: Path, items: list[dict]) -> None:
    """快照登记的文件按 sha 存进本机图缓存（`BlobCache`，`db pull` 取图也放这里）：之后当前库再变，
    本机重建这一版也不用连网。缓存里已有的跳过。"""
    from ..datastore.client import BlobCache
    cache, srcs = BlobCache(), _local_sources(ws)
    for it in items:
        if not cache.has(it["sha256"]):
            cache.put(it["sha256"], (srcs[it["root"]] / it["path"]).read_bytes())


def pins_in_use(ws: Path) -> dict[int, list[str]]:
    """工作区里各册 yaml 钉的字形库号 → 册 id。"""
    from ..core.book import load_book
    with _ws(ws):
        from ..core.workspace import books_dir
        bd = Path(books_dir())
        out: dict[int, list[str]] = {}
        for y in sorted(bd.glob("*.yaml")) if bd.is_dir() else []:
            try:
                b = load_book(y.stem, books_dir=bd)
            except Exception:
                continue
            if getattr(b, "glyph_pin", None):
                out.setdefault(int(b.glyph_pin), []).append(b.id)
    return out


def ensure_pins(ws: Path, pins=None, *, log=print) -> list[dict]:
    """有快照的钉号（缺省：各册 yaml 写到的），本机没建库或库过时就建。没快照的号（旧做法）跳过。"""
    ws = Path(ws)
    out = []
    for n in sorted(pins if pins is not None else pins_in_use(ws)):
        if load_manifest(ws, n) is None:
            continue
        r = build_pinned_db(ws, n)
        if not r.get("reused"):
            log(f"  建字形库 g{n}：{r['db']}（本机 {r.get('local', 0)}，R2 {r.get('fetched', 0)}）")
        out.append(r)
    return out


def list_pins(ws: Path) -> list[dict]:
    used = pins_in_use(ws)
    out = []
    for n in versions(ws):
        man = load_manifest(ws, n) or {}
        with _ws(ws):
            db = pinned_db_path(n)
        meta = pinned_db_meta(db)
        out.append({"pin": n, "digest": man.get("digest"), "rev": man.get("rev"), "created": man.get("created"),
                    "items": len(man.get("items", [])), "borrow": man.get("borrow", []), "note": man.get("note", ""),
                    "db": "ok" if meta and meta.get("digest") == man.get("digest") else ("stale" if meta else "missing"),
                    "books": used.get(n, [])})
    legacy = sorted(set(used) - set(versions(ws)))
    for n in legacy:
        out.append({"pin": n, "digest": None, "db": "-", "books": used[n], "note": "没有快照：只钉指纹（旧做法）"})
    return out


def _new_since_previous(ws: Path, man: dict, full: bool) -> tuple[dict, int]:
    """只留相对上一版 g<N-1> 清单新增或改动的条目（按 sha 差）。条目内容按 sha 存、不会变，上一版已上传校验过的不必再来一遍；
    没有上一版或 ``full`` 就原样返回。返回 (清单副本, 跳过的条目数)。"""
    prev = [n for n in versions(ws) if n < man["n"]]
    last = load_manifest(ws, prev[-1]) if prev and not full else None
    if last is None:
        return man, 0
    seen = {(it["root"], it["path"], it["sha256"]) for it in last["items"]}
    items = [it for it in man["items"] if (it["root"], it["path"], it["sha256"]) not in seen]
    return {**man, "items": items}, len(man["items"]) - len(items)


def upload_blobs(ws: Path, version: int, *, execute: bool = False, full: bool = False) -> dict:
    """清单里的文本、图按 sha 传 R2（已有跳过）。缺省演练；``execute`` 才传，要正式令牌 ``GUJI_DATA_TOKEN``。
    本机文件 sha 与清单不符的拒绝上传。缺省只处理相对上一版新增或改动的条目（``full`` 才全量）。"""
    ws = Path(ws)
    man = load_manifest(ws, version)
    if man is None:
        raise SystemExit(f"没有字形库 g{version} 的清单")
    man, skipped = _new_since_previous(ws, man, full)
    srcs = _local_sources(ws)
    have: dict[str, dict[str, Path]] = {"txt": {}, "png": {}}
    absent = []
    for it in man["items"]:
        base = srcs.get(it["root"])
        p = base / it["path"] if base is not None else None
        if p is not None and p.is_file() and _sha_cached(p) == it["sha256"]:
            have[it.get("type", "txt")][it["sha256"]] = p
        else:
            absent.append(f'{it["root"]}:{it["path"]}')
    plan = {"pin": version, "txt": len(have["txt"]), "png": len(have["png"]),
            "bytes": sum(p.stat().st_size for d in have.values() for p in d.values()),
            "not_local": absent[:20], "n_not_local": len(absent), "executed": False,
            "skipped_same_as_previous": skipped}
    if absent:
        plan["warning"] = "本机文件已与清单不同（出快照后又改过），这些条目只能靠 R2 里已有的"
    if execute:
        from ..datastore.r2 import upload_files
        plan["upload"] = {ext: upload_files(d, bucket="main", ext=ext) for ext, d in have.items() if d}
        plan["executed"] = True
    return plan


def verify_remote(ws: Path, version: int, src=None, *, full: bool = False) -> dict:
    """只从 R2 拼一遍（不用本机文件、也不用本机的图缓存），核对每个条目都取得到。成功即新机器能建这一版。
    缺省只核相对上一版新增或改动的条目（上一版已核过；``full`` 才全量）。"""
    import tempfile
    from ..datastore.client import BlobCache
    man = load_manifest(Path(ws), version)
    if man is None:
        raise SystemExit(f"没有字形库 g{version} 的清单")
    full_n = len(man["items"])
    man, skipped = _new_since_previous(Path(ws), man, full)
    with tempfile.TemporaryDirectory() as td:
        info = assemble(Path(ws), man, Path(td) / "g", local=False, src=src, cache=BlobCache(Path(td) / "cache"))
    return {"pin": version, "items": full_n, "checked": len(man["items"]), "skipped_same_as_previous": skipped, **info, "ok": True}
