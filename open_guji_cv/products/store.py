"""数值产物仓：products/<book>/<step_id>/<key>.json + _manifest.jsonl。

一个 key 文件里放该步产出的全部 numeric 种类：{kind_id: 产物}。
读的时候按 kind 取，schema 校验后返回 pydantic 实例。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .manifest import Manifest


def default_products_root() -> Path:
    """`GUJI_PRODUCTS_DIR` > `GUJI_WORKSPACE`/products > 仓内 products（core.workspace）。"""
    from ..core.workspace import products_root
    return products_root()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ProductStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else default_products_root()
        self._manifests: dict[tuple[str, str], Manifest] = {}
        self._raw_index_cache: dict[str, dict] = {}

    # ── 路径 ─────────────────────────────────────────────────────────
    def step_dir(self, book: str, step_id: str) -> Path:
        return self.root / book / step_id

    def path(self, book: str, step_id: str, key: str) -> Path:
        return self.step_dir(book, step_id) / f"{key}.json"

    def manifest(self, book: str, step_id: str) -> Manifest:
        k = (book, step_id)
        if k not in self._manifests:
            self._manifests[k] = Manifest(self.step_dir(book, step_id) / "_manifest.jsonl")
        return self._manifests[k]

    # ── 读写 ─────────────────────────────────────────────────────────
    def exists(self, book: str, step_id: str, key: str) -> bool:
        return self.path(book, step_id, key).exists()

    def write(self, book: str, step_id: str, key: str, products: dict[str, BaseModel]) -> tuple[Path, str]:
        """写一页的全部 numeric 产物，返回 (路径, sha256)。序列化是确定性的（键排序）。"""
        payload = {k: v.model_dump(mode="json") for k, v in products.items()}
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
        p = self.path(book, step_id, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_bytes(data)
        # 覆盖前把上一代留在 `_prev/`（只留一代）。格级复用（core/reuse.py）要拿
        # 「下游产物当时看到的那份上游」跟新上游逐格比几何——上游一旦被覆盖就没
        # 得比了。是不是"那份"由 manifest 里记的上游 sha 说了算，这里只负责留住。
        if p.exists():
            prev = self.prev_path(book, step_id, key)
            prev.parent.mkdir(parents=True, exist_ok=True)
            os.replace(p, prev)
        tmp.replace(p)
        return p, sha256_bytes(data)

    # ── 上一代产物（格级复用用）───────────────────────────────────────
    def prev_path(self, book: str, step_id: str, key: str) -> Path:
        return self.step_dir(book, step_id) / "_prev" / f"{key}.json"

    def prev_sha(self, book: str, step_id: str, key: str) -> str | None:
        p = self.prev_path(book, step_id, key)
        return sha256_file(p) if p.exists() else None

    def read_prev(self, book: str, step_id: str, key: str, kind_id: str) -> BaseModel | None:
        from ..core.step import kind_of
        p = self.prev_path(book, step_id, key)
        if not p.exists():
            return None
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if kind_id not in d:
            return None
        schema = kind_of(kind_id).schema
        assert schema is not None
        return schema.model_validate(d[kind_id])

    def read_raw(self, book: str, step_id: str, key: str) -> dict[str, Any] | None:
        p = self.path(book, step_id, key)
        if not p.exists():
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def read(self, book: str, step_id: str, key: str, kind_id: str) -> BaseModel | None:
        from ..core.step import kind_of
        d = self.read_raw(book, step_id, key)
        if d is None or kind_id not in d:
            return None
        schema = kind_of(kind_id).schema
        assert schema is not None
        return schema.model_validate(d[kind_id])

    def sha(self, book: str, step_id: str, key: str) -> str | None:
        p = self.path(book, step_id, key)
        return sha256_file(p) if p.exists() else None

    def keys(self, book: str, step_id: str) -> list[str]:
        d = self.step_dir(book, step_id)
        if not d.exists():
            return []
        return sorted(p.stem for p in d.glob("p*.json"))

    # ── 原图指纹（按 mtime+size 缓存，避免每次重算整册 sha）───────────
    def raw_sha(self, book: str, path: Path) -> str:
        idx_path = self.root / book / "_raw_index.json"
        if book not in self._raw_index_cache:
            self._raw_index_cache[book] = (
                json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {})
            self._sync_source(book, path.parent)
        idx = self._raw_index_cache[book]
        st = path.stat()
        rec = idx.get(path.name)
        if rec and rec.get("mtime") == st.st_mtime and rec.get("size") == st.st_size:
            return rec["sha256"]
        sha = sha256_file(path)
        idx[path.name] = {"mtime": st.st_mtime, "size": st.st_size, "sha256": sha}
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=0), encoding="utf-8")
        return sha

    # ── 原图出自哪一版页表（GUJI-748 换图源）────────────────────────
    SOURCE_FILE = "_source.json"

    def _sync_source(self, book: str, raw_dir: Path) -> None:
        """把原图目录里 `guji source pull` 留的页表记号（`_pages.json` 的 book_id/vol/rev）抄进本册产物目录。

        这样产物包自带「这些格是在哪一版页表的图上切的」，人裁锚的 `source_rev` 从这里取，
        不取册 yaml 的现行值（用 `--pack` 取旧图包落旧票时，不会给旧坐标盖上新 rev）。
        原图目录没有记号（手放的图、pull 之前的老目录）时删掉旧抄件，按「来历不明」处理。"""
        from ..datastore.sources import PULL_MARK
        dst = self.root / book / self.SOURCE_FILE
        try:
            mark = json.loads((raw_dir / PULL_MARK).read_text(encoding="utf-8"))
            rec = {k: mark.get(k) for k in ("book_id", "vol", "rev")}
        except (OSError, ValueError):
            rec = None
        if rec is None or rec.get("rev") is None:
            dst.unlink(missing_ok=True)
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(rec, ensure_ascii=False) + "\n"
        if not dst.exists() or dst.read_text(encoding="utf-8") != text:
            dst.write_text(text, encoding="utf-8")

    def source_rev(self, book: str) -> int | None:
        """本册产物所依页表的 rev；产物包没带来历（旧包）→ None。"""
        try:
            rev = json.loads((self.root / book / self.SOURCE_FILE).read_text(encoding="utf-8")).get("rev")
        except (OSError, ValueError):
            return None
        return None if rev is None else int(rev)
