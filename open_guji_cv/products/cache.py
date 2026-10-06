"""图像缓存：派生图像（列图、字块、归一图块）的家。不入 git、不进快照。

    cache/<book>/<kind_id>/<key>.png

`materialize(book, kind, key, builder)`：有就返回路径（顺手 touch），没有就调
builder 现算、写入、返回。`prune()` 按 mtime 做 LRU，压到上限以下。

## 页级戳（2026-10-01）

缓存文件**只按名字认**，从不比对它是从哪一版产物切出来的。引擎自己重跑一页时会先清这一页的缓存
（engine `invalidate`），但**产物被外部换掉时没人清**——从服务器 tar 回产物、`snap import`、
从备份还原——缓存里还是上一代产物切的图。实锤 vol03（2026-10-01）：本地缓存对着换进来的
行切分产物，约 16% 的列字块整体错了一格，`glyph_match` 点名重算读到邻格的图，字形库一更新
对位就在 13 页上漂移，而一切状态都显示正常。

所以每种图像类产物按页记一个**戳**（产出它的那一步这一页产物的 sha，`cache/<册>/<种类>/_stamps.json`）：
写缓存时记下、读缓存时与「现在这一页产物的 sha」比对，对不上就把这一页该种类的缓存整体清掉重算。
没有戳的老缓存照旧放行（无从验证）——要查这类用 `guji cache verify <册>`（拿渲染结果比对邻格）。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Callable

import numpy as np

from ..utils.image_io import imwrite

DEFAULT_LIMIT_BYTES = 20 * (1 << 30)   # 20 GB


def default_cache_root() -> Path:
    """`GUJI_CACHE_DIR` > `GUJI_WORKSPACE`/cache > 仓内 cache（core.workspace）。"""
    from ..core.workspace import cache_root
    return cache_root()


class ImageCache:
    def __init__(self, root: Path | None = None, limit_bytes: int = DEFAULT_LIMIT_BYTES):
        self.root = Path(root) if root else default_cache_root()
        self.limit_bytes = limit_bytes

    def path(self, book: str, kind_id: str, key: str, ext: str = "png") -> Path:
        return self.root / book / kind_id / f"{key}.{ext}"

    # ── 页级戳 ───────────────────────────────────────────────────────
    _PAGE_RE = re.compile(r"^p\d{4}")

    def _stamps_path(self, book: str, kind_id: str) -> Path:
        return self.root / book / kind_id / "_stamps.json"

    def _read_stamps(self, book: str, kind_id: str) -> dict[str, str]:
        p = self._stamps_path(book, kind_id)
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except (OSError, ValueError):
            return {}                    # 戳文件坏了 = 没戳，按老缓存放行

    def page_stamp(self, book: str, kind_id: str, key: str) -> str | None:
        m = self._PAGE_RE.match(key)
        return self._read_stamps(book, kind_id).get(m.group(0)) if m else None

    def set_page_stamp(self, book: str, kind_id: str, key: str, stamp: str | None) -> None:
        """记下这一页这一种类的缓存是对着哪一版产物切的。`stamp=None` 不动。"""
        m = self._PAGE_RE.match(key)
        if not stamp or not m:
            return
        d = self._read_stamps(book, kind_id)
        if d.get(m.group(0)) == stamp:
            return
        d[m.group(0)] = stamp
        p = self._stamps_path(book, kind_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)

    def _drop_stale_page(self, book: str, kind_id: str, key: str) -> None:
        m = self._PAGE_RE.match(key)
        self.invalidate(book, kind_id, key_prefix=m.group(0))
        d = self._read_stamps(book, kind_id)
        if d.pop(m.group(0), None) is not None:
            self._stamps_path(book, kind_id).write_text(json.dumps(d, sort_keys=True), encoding="utf-8")

    def get(self, book: str, kind_id: str, key: str, stamp: str | None = None) -> Path | None:
        """`stamp` = 这一页产物现在的 sha。缓存里记着另一个戳 → 这一页该种类缓存整体过期，清掉返回 None。
        没记戳（老缓存）→ 放行。"""
        if stamp:
            rec = self.page_stamp(book, kind_id, key)
            if rec is not None and rec != stamp:
                self._drop_stale_page(book, kind_id, key)
                return None
        p = self.path(book, kind_id, key)
        if p.exists():
            try:
                os.utime(p, None)
            except OSError:
                pass
            return p
        return None

    def put(self, book: str, kind_id: str, key: str, img: np.ndarray,
            stamp: str | None = None) -> Path:
        p = self.path(book, kind_id, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not imwrite(str(p), img):
            raise IOError(f"写缓存失败: {p}")
        self.set_page_stamp(book, kind_id, key, stamp)
        return p

    def materialize(self, book: str, kind_id: str, key: str,
                    builder: Callable[[], np.ndarray], stamp: str | None = None) -> Path:
        p = self.get(book, kind_id, key, stamp=stamp)
        if p is not None:
            return p
        img = builder()
        if img is None:
            raise RuntimeError(f"builder 没有产出图像: {kind_id} {key}")
        return self.put(book, kind_id, key, img, stamp=stamp)

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
                if p.is_file() and p.stem.startswith(key_prefix) and p.name != "_stamps.json":
                    p.unlink()
                    n += 1
            if not key_prefix:
                (d / "_stamps.json").unlink(missing_ok=True)       # 整种类清空时戳也一并作废
        return n

    def usage(self) -> tuple[int, int]:
        """(字节数, 文件数)"""
        total = n = 0
        if self.root.exists():
            for p in self.root.rglob("*"):
                if p.is_file() and p.name != "_stamps.json":     # 戳文件是元数据，不算缓存体积
                    total += p.stat().st_size
                    n += 1
        return total, n

    def prune(self, limit_bytes: int | None = None) -> int:
        """LRU 淘汰到上限以下，返回释放的字节数。"""
        limit = self.limit_bytes if limit_bytes is None else limit_bytes
        files = [(p.stat().st_mtime, p.stat().st_size, p)
                 for p in self.root.rglob("*")
                 if p.is_file() and p.name != "_stamps.json"] if self.root.exists() else []
        total = sum(s for _, s, _ in files)
        freed = 0
        for _, size, p in sorted(files):
            if total <= limit:
                break
            p.unlink()
            total -= size
            freed += size
        return freed
