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
    # opinions（P2 搬去 manager，2026-11-02）
    "data_home": ("core.workspace", "data_home"),
    "central_data_dir": ("core.workspace", "central_data_dir"),
    "CentralError": ("datastore.client", "CentralError"),
    # 册号（core/volume_id，2026-11-02）：manager 的标 main 钩子按册配置取书 id 与章号
    "volume_of": ("core.volume_id", "volume_of"),
    # source、cellvotes、freeze（P2 第二批搬去 manager，2026-11-02）：命令层在 manager，底下逻辑仍在 cv
    "feedback_root": ("core.workspace", "feedback_root"),
    "load_votes": ("feedback.web_votes", "load_votes"),
    "page_key": ("core.spec", "page_key"),
    "check_cell": ("feedback.web_votes", "check_cell"),
    "cord_boxes": ("feedback.web_votes", "cord_boxes"),
    "shrink_boxes": ("feedback.web_votes", "shrink_boxes"),
    "ProductStore": ("products.store", "ProductStore"),
    "products_root": ("core.workspace", "products_root"),
    "packs": ("datastore.packs", None),
    "EventLog": ("feedback.events", "EventLog"),
    "latest_human": ("feedback.web_votes", "latest_human"),
    "latest_votes": ("feedback.web_votes", "latest_votes"),
    "recheck_rows": ("feedback.web_votes", "recheck_rows"),
    "triage": ("feedback.web_votes", "triage"),
    "batches_root": ("core.workspace", "batches_root"),
    "verdicts_root": ("core.workspace", "verdicts_root"),
    "GoldStore": ("gold.store", "GoldStore"),
    "BatchStore": ("review.batches", "BatchStore"),
    "write_events": ("review.event_write", "write_events"),
    "cell_migrate": ("feedback.cell_migrate", None),
    "Event": ("feedback.events", "Event"),
    "book_yaml_path": ("core.book", "_book_yaml_path"),
    "freeze_register": ("ops.freeze_register", None),
    "default_products_root": ("products.store", "default_products_root"),
    "book_versions": ("cli_products", "book_versions"),
    "ws_name": ("datastore.packs", "_ws_name"),
    "norm_vol": ("datastore.sources", "norm_vol"),
    "load_book": ("core.book", "load_book"),
    "sources": ("datastore.sources", None),
    "BlobCache": ("datastore.client", "BlobCache"),
    "spreads": ("datastore.spreads", None),
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
