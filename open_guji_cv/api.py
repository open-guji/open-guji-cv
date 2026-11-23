# -*- coding: utf-8 -*-
"""pipeline 的公开面：manager 只许 import 这里与 `open_guji_cv.products.kinds`（产物 schema），
不许直接 import `clustering` / `utils` / `steps` 的内部。设计与契约见 `doc/design/拆分-pipeline与manager.md`、`doc/契约.md`。

这一层只转发现有函数，不放逻辑，所以随便什么时候改都不动 Step 指纹。
"""

from __future__ import annotations

from .core import workspace
from .core.book import BookSpec, load_book
from .core.contract import CONTRACT_VERSION
from .core.cv_version import describe as _describe
from .core.step import STEPS
from .products.manifest import Manifest, ManifestEntry
from .products.store import ProductStore

__all__ = [
    "CONTRACT_VERSION", "BookSpec", "load_book", "Manifest", "ManifestEntry", "ProductStore",
    "workspace", "version_info",
]


def version_info() -> dict:
    """`guji version --json` 的内容：装着的 pipeline 是哪个版本、讲哪一版契约。"""
    from . import steps as _steps  # noqa: F401  —— import 即注册全部 Step
    ver, commit = _describe()
    return {"cv_version": ver, "cv_commit": commit, "contract_version": CONTRACT_VERSION,
            "steps": sorted(STEPS)}
