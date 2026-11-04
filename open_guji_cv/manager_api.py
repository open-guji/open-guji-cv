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
    # 待审原因码表（manager pending-stats，2026-11-03）
    "pending_reason_specs": ("review.pending_reason", "specs"),
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
    # exp、snap、events、eval 等命令层（P2 第三批搬去 manager，2026-11-04）：底下逻辑仍在 cv
    "BadRequest": ("errors", "BadRequest"),
    "default_root": ("exp.runner", "default_root"),
    "exp_report": ("exp.report", None),
    "exp_tracking": ("exp.tracking", None),
    "read_state": ("exp.runner", "read_state"),
    "exp_flips": ("exp.flips", None),
    "exp_sample": ("exp.sample", None),
    "from_dict": ("exp.config", "from_dict"),
    "exp_config": ("exp.config", None),
    "exp_runner": ("exp.runner", None),
    "ops_release_check": ("ops.release_check", None),
    "ops_deploy_check": ("ops.deploy_check", None),
    "ArchiveError": ("ops.archive_fetch", "ArchiveError"),
    "DEFAULT_REPO": ("ops.archive_fetch", "DEFAULT_REPO"),
    "fetch": ("ops.archive_fetch", "fetch"),
    "snap_gitio": ("snap.gitio", None),
    "snap_importer": ("snap.importer", None),
    "snap_watch": ("snap.watch", None),
    "snap_pack": ("snap.pack", None),
    "workspace_root": ("core.workspace", "workspace_root"),
    "books_dir": ("core.workspace", "books_dir"),
    "snap_indexes": ("snap.indexes", None),
    "imread": ("utils.image_io", "imread"),
    "Batch": ("review.batches", "Batch"),
    "render_registry_markdown": ("review.batches", "render_registry_markdown"),
    "steps": ("steps", None),
    "review_label_batches": ("review.label_batches", None),
    "ProductMissing": ("errors", "ProductMissing"),
    "route_and_consume": ("feedback.consumers", "route_and_consume"),
    "harvest_file": ("feedback.harvest", "harvest_file"),
    "RouteTable": ("feedback.routes", "RouteTable"),
    "lint": ("feedback.lint", "lint"),
    "verdict_store": ("feedback.consumers", "verdict_store"),
    "cutline_verdicts": ("review.verdict_view", "cutline_verdicts"),
    "review_verdicts": ("review.verdict_view", "review_verdicts"),
    "out": ("cli_v2", "_out"),
    "replay_key": ("feedback.events", "replay_key"),
    "import_vision": ("feedback.vision", "import_vision"),
    "ImportFilter": ("gold.transfer", "ImportFilter"),
    "import_to_dataset": ("gold.transfer", "import_to_dataset"),
    "parse_pages": ("gold.transfer", "parse_pages"),
    "export_to_workspace": ("gold.transfer", "export_to_workspace"),
    "rebuild_verdicts": ("gold.transfer", "rebuild_verdicts"),
    "rebuild_vision_gold": ("feedback.vision", "rebuild_vision_gold"),
    "check_shard": ("gold.drift", "check_shard"),
    "mark_drifted": ("gold.drift", "mark_drifted"),
    "run_eval": ("eval", "run_eval"),
    "EVALS": ("eval.registry", "EVALS"),
    "runnable": ("eval.registry", "runnable"),
    "quality": ("eval.quality", "quality"),
    "measure": ("eval.rulers", "measure"),
    "eval_round_check": ("eval.round_check", None),
    "eval_rate_history": ("eval.rate_history", None),
    "eval_throughput": ("eval.throughput", None),
    "crosscheck": ("clustering.glyph_ledger", "crosscheck"),
    "glyph_db_path": ("core.workspace", "glyph_db_path"),
    "groups_catalog": ("groups.catalog", None),
    "eval_group_status": ("eval.group_status", None),
    "eval_group_progress": ("eval.group_progress", None),
    "cards": ("review.cards", "cards"),
    "jiazhu_segments": ("review.jiazhu_cards", "jiazhu_segments"),
    "group_view": ("review.group_view", "group_view"),
    "eval_touching": ("eval.touching", None),
    "write_html": ("report.html", "write_html"),
    "body_pages": ("report.run", "body_pages"),
    "collate_book": ("report.run", "collate_book"),
    "write_report": ("report.run", "write_report"),
    "load_witnesses": ("report.witness", "load_witnesses"),
    "write_diff_strips": ("report.strips", "write_diff_strips"),
    "write_variant_thumbs": ("report.strips", "write_variant_thumbs"),
    "format_table": ("report.progress", "format_table"),
    "page_progress": ("report.progress", "page_progress"),
    "guard_cv_version": ("cli_v2", "_guard_cv_version"),
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
