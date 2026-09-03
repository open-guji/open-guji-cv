"""图像缓存：派生图像（列图、字块、归一图块）的家。不入 git、不进快照。

    cache/<book>/<kind_id>/<key>.png

`materialize(book, kind, key, builder)`：有就返回路径（顺手 touch），没有就调
builder 现算、写入、返回。`prune()` 按 mtime 做 LRU，压到上限以下。
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..utils.image_io import imwrite

DEFAULT_LIMIT_BYTES = 20 * (1 << 30)   # 20 GB


def default_cache_root() -> Path:
    env = os.environ.get("GUJI_CACHE_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent / "cache"


class ImageCache:
    def __init__(self, root: Path | None = None, limit_bytes: int = DEFAULT_LIMIT_BYTES):
        self.root = Path(root) if root else default_cache_root()
        self.limit_bytes = limit_bytes

    def path(self, book: str, kind_id: str, key: str, ext: str = "png") -> Path:
        return self.root / book / kind_id / f"{key}.{ext}"

    def get(self, book: str, kind_id: str, key: str) -> Path | None:
        p = self.path(book, kind_id, key)
        if p.exists():
            try:
                os.utime(p, None)
            except OSError:
                pass
            return p
        return None

    def put(self, book: str, kind_id: str, key: str, img: np.ndarray) -> Path:
        p = self.path(book, kind_id, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not imwrite(str(p), img):
            raise IOError(f"写缓存失败: {p}")
        return p

    def materialize(self, book: str, kind_id: str, key: str,
                    builder: Callable[[], np.ndarray]) -> Path:
        p = self.get(book, kind_id, key)
        if p is not None:
            return p
        img = builder()
        if img is None:
            raise RuntimeError(f"builder 没有产出图像: {kind_id} {key}")
        return self.put(book, kind_id, key, img)

    def invalidate(self, book: str, kind_id: str | None = None, key_prefix: str = "") -> int:
        """删掉某册某种类（或全部种类）下 key 以 prefix 开头的缓存，返回删了几个。"""
        base = self.root / book
        if not base.exists():
            return 0
        dirs = [base / kind_id] if kind_id else [d for d in base.iterdir() if d.is_dir()]
        n = 0
        for d in dirs:
            if not d.exists():
                continue
            for p in d.iterdir():
                if p.is_file() and p.stem.startswith(key_prefix):
                    p.unlink()
                    n += 1
        return n

    def usage(self) -> tuple[int, int]:
        """(字节数, 文件数)"""
        total = n = 0
        if self.root.exists():
            for p in self.root.rglob("*"):
                if p.is_file():
                    total += p.stat().st_size
                    n += 1
        return total, n

    def prune(self, limit_bytes: int | None = None) -> int:
        """LRU 淘汰到上限以下，返回释放的字节数。"""
        limit = self.limit_bytes if limit_bytes is None else limit_bytes
        files = [(p.stat().st_mtime, p.stat().st_size, p)
                 for p in self.root.rglob("*") if p.is_file()] if self.root.exists() else []
        total = sum(s for _, s, _ in files)
        freed = 0
        for _, size, p in sorted(files):
            if total <= limit:
                break
            p.unlink()
            total -= size
            freed += size
        return freed
