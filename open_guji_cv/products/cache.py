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

戳文件是整种类一份的「读→改→写」，页级并行（`guji pipeline --jobs N`）时几个 worker 同时惰性再生
不同页的图块，都要改它：不加锁会互相覆盖（丢掉别页的戳），共用一个 `.tmp` 名还会让后一个
`os.replace` 找不到文件、整页记失败。所以改戳一律在 `_stamps_lock` 里做，临时文件带进程号。

戳还是「这一页缓存可信」的凭据：`guji cache verify`／`close-check` 1b 对戳与现行产物对得上的页
不再逐列渲染比对（2026-10-20，出口检查 5–12 分钟 → 秒级）。所以**只能给干净的页记戳**：引擎重跑一页
前先清掉这一页再写，干净；惰性补图时这一页若还没戳、目录里却已有别的图（记戳机制之前的老缓存，
是哪一代产物切的说不清），就不记——否则补一张新图会把整页老图一起「洗白」，校验从此跳过它。
"""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import numpy as np

from ..utils.image_io import imwrite

DEFAULT_LIMIT_BYTES = 20 * (1 << 30)   # 20 GB


def _is_meta(p: Path) -> bool:
    """戳文件、它的临时文件、改戳的锁文件：不是缓存图，清缓存与 LRU 都不碰。"""
    return p.name == "_stamps.json" or p.name.startswith(("_stamps.tmp", "."))


def default_cache_root() -> Path:
    """`GUJI_CACHE_DIR` > `GUJI_WORKSPACE`/cache > 仓内 cache（core.workspace）。"""
    from ..core.workspace import cache_root
    return cache_root()


class ImageCache:
    def __init__(self, root: Path | None = None, limit_bytes: int = DEFAULT_LIMIT_BYTES):
        self.root = Path(root) if root else default_cache_root()
        self.limit_bytes = limit_bytes
        #: (册, 种类, 页) → 这一页没戳时目录里是否已有老图（见模块头末段）；清页缓存时作废
        self._legacy: dict[tuple[str, str, str], bool] = {}

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
        if self._read_stamps(book, kind_id).get(m.group(0)) == stamp:
            return                               # 常见路径：已记过，不拿锁
        with self._stamps_lock(book, kind_id):
            d = self._read_stamps(book, kind_id)
            if d.get(m.group(0)) == stamp:
                return
            d[m.group(0)] = stamp
            self._write_stamps(book, kind_id, d)

    @contextmanager
    def _stamps_lock(self, book: str, kind_id: str):
        """改 `_stamps.json` 的跨进程锁（见模块头）：每种类一把，锁文件与戳文件同目录，阻塞等
        （临界区是毫秒级的读改写）。关文件即放锁，进程死了锁也就放了。"""
        from ..core.runlock import _try_lock
        d = self.root / book / kind_id
        d.mkdir(parents=True, exist_ok=True)
        with open(d / ".stamps.lock", "a+") as fh:
            _try_lock(fh, blocking=True)
            yield

    def _write_stamps(self, book: str, kind_id: str, d: dict[str, str]) -> None:
        p = self._stamps_path(book, kind_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(d, sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)

    def _drop_stale_page(self, book: str, kind_id: str, key: str) -> None:
        m = self._PAGE_RE.match(key)
        self.invalidate(book, kind_id, key_prefix=m.group(0))
        with self._stamps_lock(book, kind_id):
            d = self._read_stamps(book, kind_id)
            if d.pop(m.group(0), None) is not None:
                self._write_stamps(book, kind_id, d)

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
        m = self._PAGE_RE.match(key)
        if stamp and m and self.page_stamp(book, kind_id, key) is None \
                and self.has_unstamped_files(book, kind_id, m.group(0)):
            stamp = None                 # 这一页有说不清来历的老图：不记戳（模块头末段）
        # 先写临时文件再换上去（2026-10-20）：并行时别的 worker 可能正在读这张图（Step7 铁证
        # 会读别页的人裁刻例），直接写会让它读到半张图、整页记失败。临时名以 `.` 开头，
        # 清缓存与 LRU 都不当它是缓存图（`_is_meta`）。
        tmp = p.with_name(f".{p.stem}.tmp{os.getpid()}{p.suffix}")
        if not imwrite(str(tmp), img):
            tmp.unlink(missing_ok=True)
            raise IOError(f"写缓存失败: {p}")
        os.replace(tmp, p)
        self.set_page_stamp(book, kind_id, key, stamp)
        return p

    def has_unstamped_files(self, book: str, kind_id: str, page: str) -> bool:
        """这一页（`page` 形如 `p0024`）在记戳之前目录里就已有缓存图：首次查时看一眼目录并记住，
        之后同一页只查内存（字块目录一册几万个文件，不能每张图都扫一遍）。"""
        k = (book, kind_id, page)
        hit = self._legacy.get(k)
        if hit is None:
            d = self.root / book / kind_id
            hit = d.exists() and any(not _is_meta(q) for q in d.glob(f"{page}*"))
            self._legacy[k] = hit
        return hit

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
                if p.is_file() and p.stem.startswith(key_prefix) and not _is_meta(p):
                    p.unlink()
                    n += 1
            for k in [k for k in self._legacy if k[0] == book and k[1] == d.name and k[2].startswith(key_prefix)]:
                del self._legacy[k]
            if not key_prefix:
                (d / "_stamps.json").unlink(missing_ok=True)       # 整种类清空时戳也一并作废
        return n

    def usage(self) -> tuple[int, int]:
        """(字节数, 文件数)"""
        total = n = 0
        if self.root.exists():
            for p in self.root.rglob("*"):
                if p.is_file() and not _is_meta(p):     # 戳文件与锁是元数据，不算缓存体积
                    total += p.stat().st_size
                    n += 1
        return total, n

    def prune(self, limit_bytes: int | None = None) -> int:
        """LRU 淘汰到上限以下，返回释放的字节数。"""
        limit = self.limit_bytes if limit_bytes is None else limit_bytes
        files = [(p.stat().st_mtime, p.stat().st_size, p)
                 for p in self.root.rglob("*")
                 if p.is_file() and not _is_meta(p)] if self.root.exists() else []
        total = sum(s for _, s, _ in files)
        freed = 0
        for _, size, p in sorted(files):
            if total <= limit:
                break
            p.unlink()
            total -= size
            freed += size
        return freed
