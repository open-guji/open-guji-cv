"""产物包：一册的 products 打包存进 R2（经 guji-data Worker `/v1/packs`），新会话直接取，不再整册现算。

为什么：products 不进中心库，每个新会话要拿到「重跑前」的那份，只能从 Step1 整册重算
（殿本一册 1.5–2.5 小时）。打包后一册约十几 MB，取回是几秒到几十秒。取回的产物可以：

- 当 `guji products diff --a` 的「前」，看这次改动的前后对比；
- 当 `guji exp run --snapshot` 的上游；
- 直接放进本机 `products/` 接着增量重跑（指纹照常判：代码、参数、库变了的步照样过期，只重跑那些）。

布局（正式桶 `pack/` 之下，按名字只增不改）::

    products/<ws>/<册>/<标签>/manifest.json
    products/<ws>/<册>/<标签>/part-000.tgz …   每段 ≤ 64 MB

标签缺省 `v<cv 版本>-<UTC 时刻>`。存要正式令牌（`GUJI_DATA_TOKEN_PROD`；实验分支上存进实验桶要实验令牌），
取、列读令牌就够。包里不带 `_prev/`（上一代，只给格级复用用）和 `*.tmp`。

只当缓存用：取回时逐段核 sha256，对不上就报错，不解。产物新不新鲜照旧由引擎按指纹判，包本身不保证新鲜。
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import tarfile
import time
from pathlib import Path

PART_BYTES = 64 * 1024 * 1024
SKIP_DIRS = {"_prev"}


def _client():
    from .client import WorkerSource
    return WorkerSource()


def _bucket(src) -> str:
    from .client import is_exp_branch
    return "exp" if is_exp_branch(src.branch) else "main"


def _ws_name() -> str:
    from ..core.workspace import central_marker, workspace_root
    m = central_marker() or {}
    if m.get("ws"):
        return str(m["ws"])
    root = workspace_root()
    return (root.name if root else "ws").split("-")[0].lower()


def _prefix(ws: str, book: str) -> str:
    return f"products/{ws}/{book}"


def _call(src, method: str, key: str, **kw):
    import urllib.parse
    return src._call(method, "/v1/packs/" + urllib.parse.quote(key), query={"bucket": _bucket(src)}, **kw)


def _tar_book(root: Path, book: str, steps: list[str] | None) -> tuple[bytes, int, dict[str, int]]:
    base = Path(root) / book
    if not base.is_dir():
        raise FileNotFoundError(f"没有产物目录 {base}")
    avail = sorted(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))
    use = steps or avail
    missing = [s for s in use if s not in avail]
    if missing:
        raise FileNotFoundError(f"{base} 下没有这些步：{', '.join(missing)}")
    buf = io.BytesIO()
    n, per = 0, {}
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tf:
        for f in sorted(base.glob("*")):                         # 册级文件（_raw_index.json 等）
            if f.is_file() and not f.name.endswith(".tmp"):
                tf.add(f, arcname=f"{book}/{f.name}")
                n += 1
        for s in use:
            k = 0
            for f in sorted((base / s).rglob("*")):
                rel = f.relative_to(base / s)
                if not f.is_file() or f.name.endswith(".tmp") or (rel.parts and rel.parts[0] in SKIP_DIRS):
                    continue
                tf.add(f, arcname=f"{book}/{s}/{rel.as_posix()}")
                k += 1
            per[s], n = k, n + k
    return buf.getvalue(), n, per


def push_products(book: str, root: Path, label: str | None = None, steps: list[str] | None = None,
                  note: str = "", src=None) -> dict:
    from ..core import cv_version as CV
    src = src or _client()
    ver, commit = CV.describe()
    label = label or f"v{ver or 'unknown'}-{time.strftime('%Y%m%dT%H%M', time.gmtime())}"
    ws = _ws_name()
    pre = f"{_prefix(ws, book)}/{label}"
    data, nfiles, per = _tar_book(root, book, steps)
    parts = []
    for i in range(0, max(1, len(data)), PART_BYTES):
        chunk = data[i:i + PART_BYTES]
        name = f"part-{len(parts):03d}.tgz"
        _call(src, "PUT", f"{pre}/{name}", data=chunk, content_type="application/gzip", tries=3)
        parts.append({"name": name, "bytes": len(chunk), "sha256": hashlib.sha256(chunk).hexdigest()})
    man = {"name": pre, "ws": ws, "book": book, "label": label, "cv_version": ver, "cv_commit": commit,
           "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "note": note,
           "files": nfiles, "steps": per, "bytes": len(data), "parts": parts,
           "pack_sha256": hashlib.sha256(data).hexdigest()}
    _call(src, "PUT", f"{pre}/manifest.json", data=json.dumps(man, ensure_ascii=False, indent=1).encode("utf-8"),
          content_type="application/json", tries=3)
    return man


def list_packs(book: str | None = None, src=None) -> list[dict]:
    src = src or _client()
    ws = _ws_name()
    pre = _prefix(ws, book) + "/" if book else f"products/{ws}/"
    rows = src._call("GET", "/v1/packs", query={"bucket": _bucket(src), "prefix": pre})["packs"]
    out = []
    for r in rows:
        if r["key"].endswith("/manifest.json"):
            try:
                m = json.loads(_call(src, "GET", r["key"], raw=True))
            except Exception:
                m = {}
            out.append({"name": r["key"][:-len("/manifest.json")], "bytes": m.get("bytes"),
                        "created": m.get("created"), "note": m.get("note", ""), "cv_version": m.get("cv_version")})
    return sorted(out, key=lambda m: m.get("created") or "")


def _latest(book: str, src) -> str:
    rows = list_packs(book, src=src)
    if not rows:
        raise FileNotFoundError(f"R2 里没有 {book} 的产物包（guji products pack list 看看）")
    return rows[-1]["name"]


def fetch_products(book: str, dest_root: Path, label: str | None = None, force: bool = False, src=None) -> dict:
    """取回并解到 `<dest_root>/<册>/`。目标已有该册产物时，除非 `force`，拒绝（不覆盖本机正在用的产物）。"""
    src = src or _client()
    name = f"{_prefix(_ws_name(), book)}/{label}" if label else _latest(book, src)
    man = json.loads(_call(src, "GET", f"{name}/manifest.json", raw=True))
    dest = Path(dest_root) / book
    if dest.exists() and any(dest.iterdir()) and not force:
        raise FileExistsError(f"{dest} 已有产物；要覆盖加 --force，或用 --to 解到别处（如对比用的空目录）")
    buf = io.BytesIO()
    for p in man["parts"]:
        chunk = _call(src, "GET", f"{name}/{p['name']}", raw=True)
        if hashlib.sha256(chunk).hexdigest() != p["sha256"]:
            raise ValueError(f"{name}/{p['name']} sha256 对不上，包坏了，不解")
        buf.write(chunk)
    buf.seek(0)
    if dest.exists():                       # 全部段核过 sha 才动本机产物
        shutil.rmtree(dest)
    Path(dest_root).mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=buf, mode="r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile() or m.name.startswith("/") or ".." in Path(m.name).parts or not m.name.startswith(f"{book}/"):
                raise ValueError(f"包里有不合规的路径：{m.name}")
        tf.extractall(dest_root, filter="data") if hasattr(tarfile, "data_filter") else tf.extractall(dest_root)
    return {"name": name, "dest": str(dest), "files": man["files"], "cv_version": man.get("cv_version")}


# ---- 生僻字 embedding 索引（Step5-b 冷建：29k 字，云上 4 核 40 分钟以上）----
# 键按内容算（checkpoint + 字体集 + 字表，`cnn_candidates.emb_index_key`），各机器同一份输入得到同一个文件名，
# 所以按文件名存取就行：`rare-index/<checkpoint 目录>/emb_<key>.npz/{part-000, manifest.json}`。

def _models_root() -> Path:
    return Path(__file__).resolve().parents[2] / "models"


def push_file(key: str, path: Path, src=None) -> dict:
    src = src or _client()
    data = Path(path).read_bytes()
    parts = []
    for i in range(0, max(1, len(data)), PART_BYTES):
        chunk = data[i:i + PART_BYTES]
        name = f"part-{len(parts):03d}"
        _call(src, "PUT", f"{key}/{name}", data=chunk, tries=3)
        parts.append({"name": name, "bytes": len(chunk), "sha256": hashlib.sha256(chunk).hexdigest()})
    man = {"name": key, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "parts": parts,
           "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _call(src, "PUT", f"{key}/manifest.json", data=json.dumps(man).encode("utf-8"),
          content_type="application/json", tries=3)
    return man


def fetch_file(key: str, dest: Path, src=None) -> int:
    src = src or _client()
    man = json.loads(_call(src, "GET", f"{key}/manifest.json", raw=True))
    data = b"".join(_call(src, "GET", f"{key}/{p['name']}", raw=True) for p in man["parts"])
    if hashlib.sha256(data).hexdigest() != man["sha256"]:
        raise ValueError(f"{key} sha256 对不上，不落盘")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return len(data)


def push_rare_indexes(src=None) -> list[str]:
    """本机 models/*/emb_*.npz 里 R2 还没有的，存上去。"""
    src = src or _client()
    have = {r["key"].rsplit("/", 1)[0] for r in
            src._call("GET", "/v1/packs", query={"bucket": _bucket(src), "prefix": "rare-index/"})["packs"]
            if r["key"].endswith("/manifest.json")}
    done = []
    for f in sorted(_models_root().glob("*/emb_*.npz")):
        key = f"rare-index/{f.parent.name}/{f.name}"
        if key not in have:
            push_file(key, f, src=src)
            done.append(key)
    return done


def fetch_rare_indexes(src=None) -> list[str]:
    """R2 里有、本机 checkpoint 目录在、文件还没有的索引，取下来。"""
    src = src or _client()
    got = []
    rows = src._call("GET", "/v1/packs", query={"bucket": _bucket(src), "prefix": "rare-index/"})["packs"]
    for r in rows:
        if not r["key"].endswith("/manifest.json"):
            continue
        key = r["key"].rsplit("/", 1)[0]
        _, ckpt, fname = key.split("/", 2)
        dest = _models_root() / ckpt / fname
        if (_models_root() / ckpt).is_dir() and not dest.exists():
            fetch_file(key, dest, src=src)
            got.append(str(dest))
    return got


# ---- 派生缓存：训好的语言模型（2026-10-20）----
# 本机缓存 `cache_root()/general_lm/<kind>-<键>.json` 的键已经按「语料内容 sha256 + 训练参数 + lm.py
# 代码指纹」算（`clustering.seeding._cached_lm`），各机器同一份输入得到同一个文件名，所以按文件名存取：
# `derived/lm/<文件名>/{part-000, manifest.json}`。取：本机没命中时自动取（要 `GUJI_DATA_TOKEN`，读令牌就够）；
# 存：手动 `guji products pack push-index`（要正式令牌），用户 10-20 定不自动推。

def _lm_dir() -> Path:
    from ..core.workspace import cache_root
    return cache_root() / "general_lm"


def fetch_derived(kind_dir: str, name: str, dest: Path) -> bool:
    """R2 里有 `derived/<kind_dir>/<name>` 就取下来（核 sha256、原子落盘）返回 True；没设令牌、
    没有这份、网络出错都返回 False（调用方接着现算，不因取不到而失败）。`GUJI_DERIVED_FETCH=0` 关掉。"""
    import os
    if not os.environ.get("GUJI_DATA_TOKEN") or os.environ.get("GUJI_DERIVED_FETCH") == "0":
        return False
    try:
        fetch_file(f"derived/{kind_dir}/{name}", Path(dest))
        return True
    except Exception:  # noqa: BLE001 —— 取不到就现算
        return False


def push_derived(src=None) -> list[str]:
    """本机训好的语言模型（`cache_root()/general_lm/*.json`）里 R2 还没有的，存上去。"""
    src = src or _client()
    have = {r["key"].rsplit("/", 1)[0] for r in
            src._call("GET", "/v1/packs", query={"bucket": _bucket(src), "prefix": "derived/lm/"})["packs"]
            if r["key"].endswith("/manifest.json")}
    done = []
    for f in sorted(_lm_dir().glob("*.json")):
        if ".tmp" in f.name or not (f.name.startswith("book-") or f.name.startswith("general-")):
            continue
        key = f"derived/lm/{f.name}"
        if key not in have:
            push_file(key, f, src=src)
            done.append(key)
    return done
