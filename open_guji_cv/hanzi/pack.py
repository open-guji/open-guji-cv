# -*- coding: utf-8 -*-
"""按清单把两个包落成本机 sqlite（总设计 §6.1、B7）。

- 清单在 git：`config/hanzi/manifest.json` 是当前版，`config/hanzi/versions/<版本>.json` 是历次版本。
- 文件按 sha 认：仓里有、sha 对得上就直接读（核心包 tsv、形近对表）；否则从本机 blob 缓存读，
  再没有就从 R2 公开域名按 sha 下载（`https://blob.open-guji.com/sha256/<2>/<sha>.txt`，不要令牌），下完核 sha。
- 灌好的库在 `$GUJI_DATA_HOME/_shared/hanzi/<版本>/{core,parts}.sqlite`，同版本只灌一次。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import urllib.request
from collections.abc import Callable
from pathlib import Path

from . import importers as I
from . import schema as S
from .build import HANZI_CFG, data_root, sha256_file

REPO = Path(__file__).resolve().parents[2]
BLOB_URL = "https://blob.open-guji.com"


def blob_cache_path(sha: str, blob_dir: Path | None = None) -> Path:
    return Path(blob_dir or data_root() / "blobs") / sha[:2] / f"{sha}.txt"


def blob_url(sha: str) -> str:
    base = os.environ.get("GUJI_BLOB_URL", BLOB_URL).rstrip("/")
    return f"{base}/sha256/{sha[:2]}/{sha}.txt"


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "open-guji-cv hanzi-db"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def _lf_sha(p: Path) -> str:
    """仓里文件的 sha：先把 CRLF 统一成 LF。Windows 的 git（`* text=auto`）检出时会把 tsv 换成 CRLF，
    清单记的是 LF 版的 sha；灌库读文本时换行本来就统一，内容一样。"""
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def get_blob(sha: str, blob_dir: Path | None = None, fetch: Callable[[str], bytes] | None = None,
             label: str = "") -> Path:
    """按 sha 取一个文件：本机 blob 缓存有且 sha 对就用，否则从 R2 公开域名下载、核 sha、落缓存。"""
    bp = blob_cache_path(sha, blob_dir)
    if bp.exists() and sha256_file(bp) == sha:
        return bp
    data = (fetch or _download)(blob_url(sha))
    if hashlib.sha256(data).hexdigest() != sha:
        raise ValueError(f"{label or sha} 下载内容的 sha256 对不上清单（{blob_url(sha)}）")
    bp.parent.mkdir(parents=True, exist_ok=True)
    tmp = bp.with_suffix(f".part{os.getpid()}")
    tmp.write_bytes(data)
    tmp.replace(bp)
    return bp


def read_manifest(version: str | None = None, repo: Path = REPO) -> dict:
    base = Path(repo) / HANZI_CFG
    p = base / "manifest.json" if not version else base / "versions" / f"{version}.json"
    if not p.exists():
        raise FileNotFoundError(f"没有 hanzi 库清单 {p}")
    return json.loads(p.read_text(encoding="utf-8"))


class Pack:
    """一个版本的两个包。`fetch(url) -> bytes` 可换（测试用假的，不联网）。"""

    def __init__(self, version: str | None = None, repo: Path = REPO, root: Path | None = None,
                 fetch: Callable[[str], bytes] | None = None):
        self.repo = Path(repo)
        self.manifest = read_manifest(version, self.repo)
        self.version = self.manifest["version"]
        self.root = Path(root) if root else data_root()
        self.fetch = fetch or _download

    def db_path(self, pack: str) -> Path:
        return self.root / self.version / f"{pack}.sqlite"

    def has(self, pack: str) -> bool:
        return self.db_path(pack).exists()

    def _file(self, key: str, f: dict) -> Path:
        """清单里的一个文件 → 本机路径（仓里 → blob 缓存 → 下载），sha 必须对上。"""
        local = self.repo / (f.get("path") or (HANZI_CFG / key))
        if local.exists() and _lf_sha(local) == f["sha256"]:
            return local
        return get_blob(f["sha256"], self.root / "blobs", self.fetch, label=key)

    def ensure(self, pack: str) -> Path:
        """把 `pack`（core／parts）灌成本机 sqlite，返回路径；已有就直接返回。"""
        dest = self.db_path(pack)
        if dest.exists():
            return dest
        tables: dict[str, list] = {}
        for key, f in sorted(self.manifest["files"].items()):
            if f["pack"] != pack:
                continue
            t = f["table"]
            text = self._file(key, f).read_text(encoding="utf-8")
            if "path" in f:                                  # 形近对表：原样的仓里表，现解析
                rows = I.near_pairs(text, key)[0]
            else:
                rows = [tuple(_parse(c, v) for c, v in zip(S.TABLES[t], line.split("\t")))
                        for line in text.splitlines()]
            tables.setdefault(t, []).extend(rows)
        write_db(dest, tables, {"version": self.version, "pack": pack,
                                "unihan_version": self.manifest.get("unihan_version", "")})
        return dest


def write_db(dest: Path, tables: dict[str, list[tuple]], meta: dict[str, str]) -> Path:
    """`{表: 行}` → sqlite（建表、灌行、建索引、写 meta），先写临时文件再换上，半截的库不会留下。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(f".tmp{os.getpid()}")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    for t, rows in tables.items():
        cols = S.TABLES[t]
        con.execute(f"CREATE TABLE {t} ({', '.join(f'{c} {_coltype(c)}' for c in cols)})")
        con.executemany(f"INSERT INTO {t} VALUES ({','.join('?' * len(cols))})", rows)
        for sql in S.INDEXES.get(t, ()):
            con.execute(sql)
    con.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    con.executemany("INSERT INTO meta VALUES (?, ?)", sorted(meta.items()))
    con.commit()
    con.close()
    tmp.replace(dest)
    return dest


def _coltype(c: str) -> str:
    return "INTEGER" if c in S.INT_COLS else "REAL" if c in S.REAL_COLS else "TEXT"


def _parse(col: str, v: str):
    if col in S.INT_COLS:
        return int(v) if v else 0
    if col in S.REAL_COLS:
        return float(v) if v else 0.0
    return v
