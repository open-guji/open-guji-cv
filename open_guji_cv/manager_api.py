# -*- coding: utf-8 -*-
"""guji-manager 过渡期用 cv 内部的唯一入口（门面）。设计见 `doc/design/拆分-pipeline与manager.md`。

用户 10-27 允许拆分过渡期 manager 直接用 cv 内部；为了让这些用法看得见、cv 改名时当场红，
manager 包（`guji_manager/`）**只许** `from open_guji_cv.api import …`（pipeline 公开面）
或 `from open_guji_cv.manager_api import …`；守卫在 guji-manager 仓 `tests/test_cv_surface.py`。
cv 这边 `tests/test_architecture.py::test_manager_facade_exports_resolve` 保证登记的名字都取得到。

每批搬迁（P2–P5）把搬过去的代码要用的 cv 名字登记进来；那些名字本身搬去 manager 后从这里删。
机制同 `console_api`：一张表加 `__getattr__`，按名字现取（惰性、不缓存，monkeypatch 照样生效）。
这一层只转发，不放逻辑；不在任何 Step 的 `code_deps` 里，改它不动指纹。
"""
from __future__ import annotations

import importlib
from typing import Any

_PKG = "open_guji_cv"

#: 对外名字 → (cv 内模块, 属性名)。属性名为 None 表示导出模块本身。
_EXPORTS: dict[str, tuple[str, str | None]] = {
    # datastore（P5 搬去 manager 后从这里删）
    "connect": ("datastore.connect", "connect"),
    "WorkerSource": ("datastore.client", "WorkerSource"),
    # groups（pipeline）
    "groups_of": ("groups.registry", "groups_of"),
    # 册号（core/volume_id，2026-11-02）：manager 的标 main 钩子按册配置取书 id 与章号
    "volume_of": ("core.volume_id", "volume_of"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        mod, attr = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"open_guji_cv.manager_api 没有导出 {name!r}"
                             f"（guji-manager 只许用这里登记过的名字，见模块头）") from None
    m = importlib.import_module(f"{_PKG}.{mod}")
    return m if attr is None else getattr(m, attr)


def __dir__() -> list[str]:
    return __all__
