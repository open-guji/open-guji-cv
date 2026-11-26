# -*- coding: utf-8 -*-
"""派生缓存（语言模型、字体字形包等）的"别处已算好的同键副本"取法（2026-10-27 拆分 M3）。

键相同即内容相同，所以取不取只影响快慢，不影响产物。pipeline 自己不联网：

1. 先看本机目录 `GUJI_DERIVED_DIR/<kind>/<name>`（manager 的 prep 预先从 R2 取好放这里）；
2. 再用进程里注册的取法 `FETCHER`（过渡期 `guji` 命令入口注册 `datastore.packs.fetch_derived`；M4 后由 manager 的 prep 取代）；
3. 都没有返回 False，调用方照旧现算。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable

DIR_ENV = "GUJI_DERIVED_DIR"

#: `(kind_dir, name, dest) -> bool`；由入口（`cli_v2.main`）或 manager 注册
FETCHER: Callable[[str, str, Path], bool] | None = None


def fetch_derived(kind_dir: str, name: str, dest: Path) -> bool:
    d = os.environ.get(DIR_ENV)
    if d:
        src = Path(d) / kind_dir / name
        if src.is_file():
            dest = Path(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            shutil.copyfile(src, tmp)
            tmp.replace(dest)
            return True
    return bool(FETCHER and FETCHER(kind_dir, name, Path(dest)))


# ── 字块按页取回（2026-11-25，CV0「字块随包存 R2」）──────────────────────────
#: 缓存不在时可以去别处整页取回的图像种类。只管字块：识字、定字只读它；列图只在切字里用，切字单本来就现算。
PAGE_KINDS = frozenset({"char_patch"})

#: `(book_id, kind_id, page, chain_fp, cache, stamp) -> bool`：按链指纹取回这一页这一种类的全部图，
#: 核对后写进 `cache`（`ImageCache.put_bytes`，带 `stamp`）。由 manager 注册；没注册、没取到返回 False，调用方照旧现算。
#: 键相同即内容相同（链指纹含产出它的那一步及全部上游这一页的指纹），所以取不取只影响快慢，不影响产物。
PAGE_FETCHER: Callable | None = None


def page_fetch_enabled() -> bool:
    return PAGE_FETCHER is not None and os.environ.get("GUJI_PATCH_FETCH", "1") not in ("0", "false", "no", "off")
