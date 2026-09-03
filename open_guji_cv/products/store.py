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
    env = os.environ.get("GUJI_PRODUCTS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent / "products"


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
        tmp.replace(p)
        return p, sha256_bytes(data)

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
