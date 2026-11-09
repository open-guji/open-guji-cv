"""书级代码（书仓 `code/`）能用的 cv 公开面（2026-11-09，`doc/design/书级代码.md`）。

书级模块只许 import `open_guji_cv.seg`（看图原语）和本模块；这里列的名字改签名或删掉算 cv MINOR。
"""
from __future__ import annotations

from .core.spec import page_key

__all__ = ["page_key"]
