# -*- coding: utf-8 -*-
"""控制台用 cv 的唯一入口（门面）。设计见 `doc/design/拆分-控制台独立成包与上网站.md` 第四节。

控制台（将来是独立包 `guji-console`）**只许** `from open_guji_cv.console_api import …`，
不许直接 import cv 的其它内部；守卫在 `tests/test_architecture.py::test_console_only_uses_facade`。
会写工作区（事件以外）或耗时的动作不在这里，控制台一律子进程调 `guji` 命令行。

## 为什么是一张表加 `__getattr__`，而不是一排 `from x import y`

1. **惰性**：控制台原来的 import 很多写在函数里（字形库、生僻字、torch 相关模块很重），
   门面要是在顶部全 import，起控制台就把这些全拖进来。这里按名字现取，用到才 import。
2. **不缓存**：每次取名都回原模块现读，测试里 `monkeypatch.setattr("open_guji_cv.x.y", …)`
   照样对控制台生效（原来函数内惰性 import 就是这个语义）。

这一层只转发，不放逻辑；不在任何 Step 的 `code_deps` 里，改它不动指纹。
名字的归属（pipeline / manager）见设计第四节；manager 一侧的将来原名改由 `guji_manager.api` 提供。
"""
from __future__ import annotations

import importlib
from typing import Any

_PKG = "open_guji_cv"

#: 对外名字 → (cv 内模块, 属性名)。属性名为 None 表示导出模块本身。
#: 加名字前先想：控制台真的要在进程里做这件事吗？会写盘或耗时的改走命令行（设计第五节）。
_EXPORTS: dict[str, tuple[str, str | None]] = {
    # api（pipeline 公开面）：控制台启动时核契约版本
    "CONTRACT_VERSION": ("core.contract", 'CONTRACT_VERSION'),
    "version_info": ("api", 'version_info'),
    # clustering.cnn_candidates
    "cnn_candidates": ("clustering.cnn_candidates", None),
    # clustering.confusables
    "confusable_pairs": ("clustering.confusables", 'load_pairs'),
    # clustering.glyph_db
    "GlyphDB": ("clustering.glyph_db", 'GlyphDB'),
    # clustering.glyph_ledger
    "char_detail": ("clustering.glyph_ledger", 'char_detail'),
    "char_table": ("clustering.glyph_ledger", 'char_table'),
    "library_summary": ("clustering.glyph_ledger", 'library_summary'),
    # clustering.glyph_selfcheck
    "FLAG_LABELS": ("clustering.glyph_selfcheck", 'FLAG_LABELS'),
    "FONT_SETS": ("clustering.glyph_selfcheck", 'FONT_SETS'),
    "STALE_MSG": ("clustering.glyph_selfcheck", 'STALE_MSG'),
    "decisions": ("clustering.glyph_selfcheck", 'decisions'),
    "font_renderer": ("clustering.glyph_selfcheck", 'font_renderer'),
    "freshness": ("clustering.glyph_selfcheck", 'freshness'),
    "load_findings": ("clustering.glyph_selfcheck", 'load_findings'),
    "out_dir": ("clustering.glyph_selfcheck", 'out_dir'),
    # clustering.ids_lookup
    "lookup": ("clustering.ids_lookup", 'lookup'),
    "warm": ("clustering.ids_lookup", 'warm'),
    # clustering.normalize
    "normalize_patch": ("clustering.normalize", 'normalize_patch'),
    # clustering.rare_panel
    "font_index_status": ("clustering.rare_panel", 'font_index_status'),
    "ids_fallback": ("clustering.rare_panel", 'ids_fallback'),
    "rare_batch": ("clustering.rare_panel", 'rare_batch'),
    "rare_for": ("clustering.rare_panel", 'rare_for'),
    "rare_patch": ("clustering.rare_panel", 'rare_patch'),
    "warm_font_index": ("clustering.rare_panel", 'warm_font_index'),
    # clustering.seeding
    "cached_matcher_from_db": ("clustering.seeding", 'cached_matcher_from_db'),
    # clustering.variant_sources
    "shared_zi": ("clustering.variant_sources", 'shared_zi'),
    # core.anchor
    "x_tr_to_tl": ("core.anchor", 'x_tr_to_tl'),
    # core.book
    "list_books": ("core.book", 'list_books'),
    "load_book": ("core.book", 'load_book'),
    # core.engine
    "Engine": ("core.engine", 'Engine'),
    # core.event_files
    "book_source_rev": ("core.event_files", 'book_source_rev'),
    "sibling_books_dir": ("core.event_files", 'sibling_books_dir'),
    # core.pipeline
    "default_pipeline_id": ("core.pipeline", 'default_pipeline_id'),
    "list_pipelines": ("core.pipeline", 'list_pipelines'),
    "load_pipeline": ("core.pipeline", 'load_pipeline'),
    # core.spec
    "cell_key": ("core.spec", 'cell_key'),
    "column_key": ("core.spec", 'column_key'),
    "page_key": ("core.spec", 'page_key'),
    # core.step
    "KINDS": ("core.step", 'KINDS'),
    "RunContext": ("core.step", 'RunContext'),
    "STEPS": ("core.step", 'STEPS'),
    # core.workspace
    "GLYPH_DB_REL": ("core.workspace", 'GLYPH_DB_REL'),
    "ROOT_ENV": ("core.workspace", 'ROOT_ENV'),
    "assert_workspace_declared": ("core.workspace", 'assert_workspace_declared'),
    "batches_root": ("core.workspace", 'batches_root'),
    "corpus_path": ("core.workspace", 'corpus_path'),
    "describe": ("core.workspace", 'describe'),
    "discover_workspaces": ("core.workspace", 'discover_workspaces'),
    "feedback_root": ("core.workspace", 'feedback_root'),
    "glyph_db_path": ("core.workspace", 'glyph_db_path'),
    "glyph_store_path": ("core.workspace", 'glyph_store_path'),
    "reports_root": ("core.workspace", 'reports_root'),
    "reset_workspace_override": ("core.workspace", 'reset_workspace_override'),
    "set_workspace_override": ("core.workspace", 'set_workspace_override'),
    "using_sample_corpus": ("core.workspace", 'using_sample_corpus'),
    "using_sample_db": ("core.workspace", 'using_sample_db'),
    "verdicts_root": ("core.workspace", 'verdicts_root'),
    "workspace_id": ("core.workspace", '_ws_id'),
    "workspace_root": ("core.workspace", 'workspace_root'),
    "workspaces_root": ("core.workspace", 'workspaces_root'),
    # errors
    "BadRequest": ("errors", 'BadRequest'),
    "Conflict": ("errors", 'Conflict'),
    "EncodeFailed": ("errors", 'EncodeFailed'),
    "GujiError": ("errors", 'GujiError'),
    "ImageMissing": ("errors", 'ImageMissing'),
    "IndexNotBuilt": ("errors", 'IndexNotBuilt'),
    "NotFound": ("errors", 'NotFound'),
    "ProductMissing": ("errors", 'ProductMissing'),
    "Unsupported": ("errors", 'Unsupported'),
    # eval.colgeom
    "current_geom": ("eval.colgeom", 'current_geom'),
    # eval.llm_online_accuracy
    "compute_report": ("guji_manager.eval.llm_online_accuracy", 'compute_report'),
    "load_online_calls": ("guji_manager.eval.llm_online_accuracy", 'load_online_calls'),
    # eval.quality
    "quality": ("guji_manager.eval.quality", 'quality'),
    # eval.rate_history
    "rate_history": ("guji_manager.eval.rate_history", None),
    # eval.registry
    "EVALS": ("guji_manager.eval.registry", 'EVALS'),
    "runnable": ("guji_manager.eval.registry", 'runnable'),
    # eval.round_check
    "round_check": ("guji_manager.eval.round_check", None),
    # eval.rulers
    "measure": ("eval.rulers", 'measure'),
    # eval.throughput
    "throughput": ("guji_manager.eval.throughput", None),
    # eval.touching
    "touching": ("guji_manager.eval.touching", None),
    # feedback.anchor
    "enrich_events": ("feedback.anchor", 'enrich_events'),
    # feedback.candidates
    "candidates": ("guji_manager.feedback.candidates", None),
    # feedback.cell_review
    "cell_review": ("guji_manager.feedback.cell_review", None),
    # feedback.collate_consumers
    "DENY_REL": ("guji_manager.feedback.collate_consumers", 'DENY_REL'),
    "collate_repo_path": ("guji_manager.feedback.collate_consumers", '_repo_path'),
    "jiajie_rows": ("guji_manager.feedback.collate_consumers", 'jiajie_rows'),
    # feedback.collate_state
    "CATS": ("guji_manager.feedback.collate_state", 'CATS'),
    "CONV_KIND_CAT": ("guji_manager.feedback.collate_state", 'CONV_KIND_CAT'),
    "SEG_FLAGS": ("guji_manager.feedback.collate_state", 'SEG_FLAGS'),
    "VIA": ("guji_manager.feedback.collate_state", 'VIA'),
    "WHO": ("guji_manager.feedback.collate_state", 'WHO'),
    "build_items": ("guji_manager.feedback.collate_state", 'build_items'),
    "counts": ("guji_manager.feedback.collate_state", 'counts'),
    "final_char": ("guji_manager.feedback.collate_state", 'final_char'),
    "group_items": ("guji_manager.feedback.collate_state", 'group_items'),
    "human_verdicts": ("guji_manager.feedback.collate_state", 'human_verdicts'),
    "seg_flags": ("guji_manager.feedback.collate_state", 'seg_flags'),
    "seg_payload": ("guji_manager.feedback.collate_state", 'seg_payload'),
    # feedback.consumers
    "route_and_consume": ("guji_manager.feedback.consumers", 'route_and_consume'),
    # feedback.events
    "EventLog": ("feedback.events", 'EventLog'),
    "EventTarget": ("feedback.events", 'EventTarget'),
    "make_event": ("feedback.events", 'make_event'),
    "replay_key": ("feedback.events", 'replay_key'),
    # feedback.figures
    "figures": ("guji_manager.feedback.figures", None),
    # feedback.harvest
    "harvest_text": ("guji_manager.feedback.harvest", 'harvest_text'),
    "parse_card_id": ("guji_manager.feedback.harvest", 'parse_card_id'),
    # feedback.routes
    "RouteTable": ("guji_manager.feedback.routes", 'RouteTable'),
    # gates.query
    "GATES": ("gates.query", 'GATES'),
    "gate_summary": ("gates.query", 'gate_summary'),
    # gold.store
    "GoldStore": ("gold.store", 'GoldStore'),
    # products.cache
    "ImageCache": ("products.cache", 'ImageCache'),
    # products.store
    "ProductStore": ("products.store", 'ProductStore'),
    # render.approx
    "APPROX_MODES": ("guji_manager.render.approx", 'APPROX_MODES'),
    "book_marks": ("guji_manager.render.approx", 'book_marks'),
    "inline_ids_map": ("guji_manager.render.approx", 'inline_ids_map'),
    "sidecar_rows": ("guji_manager.render.approx", 'sidecar_rows'),
    # render.guji_markdown
    "render_page": ("guji_manager.render.guji_markdown", 'render_page'),
    # render.overlay
    "encode_png": ("guji_manager.render.overlay", 'encode_png'),
    "overlay": ("guji_manager.render.overlay", 'overlay'),
    "preclean_overlay": ("guji_manager.render.overlay", 'preclean_overlay'),
    "preclean_report": ("guji_manager.render.overlay", 'preclean_report'),
    # render.reading_layout
    "DEFAULT_BASELINE_KG": ("guji_manager.render.reading_layout", 'DEFAULT_BASELINE_KG'),
    "reflow_page_structured": ("guji_manager.render.reading_layout", 'reflow_page_structured'),
    # report.progress
    "page_progress": ("guji_manager.report.progress", 'page_progress'),
    # report.tiers
    "JIAJIE_REL": ("report.tiers", 'JIAJIE_REL'),
    "tier_of": ("report.tiers", 'tier_of'),
    "tier_pairs": ("report.tiers", 'load_pairs'),
    # review.alt_cands
    "alt_for_image": ("guji_manager.review.alt_cands", 'alt_for_image'),
    "pivots_of": ("guji_manager.review.alt_cands", 'pivots_of'),
    # review.batches
    "Batch": ("guji_manager.review.batches", 'Batch'),
    "BatchStore": ("guji_manager.review.batches", 'BatchStore'),
    "render_registry_markdown": ("guji_manager.review.batches", 'render_registry_markdown'),
    # review.border_cards
    "border_cards": ("guji_manager.review.border_cards", None),
    # review.borrow_first
    "first_pick_mode": ("guji_manager.review.borrow_first", 'first_pick_mode'),
    # review.cards
    "REPLACE_ALIGN_SUB_KEYS": ("guji_manager.review.cards", 'REPLACE_ALIGN_SUB_KEYS'),
    "align_ref_maps": ("guji_manager.review.cards", '_align_ref_maps'),
    "blocking_cutline_cases": ("guji_manager.review.cards", 'blocking_cutline_cases'),
    "cached_cards": ("guji_manager.review.cards", 'cached_cards'),
    "cards": ("guji_manager.review.cards", 'cards'),
    "parse_cells_spec": ("guji_manager.review.cards", 'parse_cells_spec'),
    "parse_class_filter": ("guji_manager.review.cards", 'parse_class_filter'),
    "parse_doubt_filter": ("guji_manager.review.cards", 'parse_doubt_filter'),
    # review.cell_shrink_rand
    "rand_sample": ("guji_manager.review.cell_shrink_rand", 'rand_sample'),
    # review.cutline_default
    "attach_default_pick": ("guji_manager.review.cutline_default", 'attach_default_pick'),
    "cutline_default_mode": ("guji_manager.review.cutline_default", 'cutline_default_mode'),
    # review.event_write
    "write_events": ("guji_manager.review.event_write", 'write_events'),
    # review.group_view
    "group_view": ("guji_manager.review.group_view", 'group_view'),
    # review.invert_cards
    "invert_cards": ("guji_manager.review.invert_cards", None),
    # review.jiazhu_cards
    "jiazhu_segments": ("guji_manager.review.jiazhu_cards", 'jiazhu_segments'),
    # review.shadow
    "shadow_sig": ("guji_manager.review.shadow", 'shadow_sig'),
    # review.slot_count_cards
    "render_slot_count_img": ("guji_manager.review.slot_count_cards", 'render_slot_count_img'),
    "slot_count_cards": ("guji_manager.review.slot_count_cards", 'slot_count_cards'),
    # review.verdict_view
    "cutline_verdicts": ("guji_manager.review.verdict_view", 'cutline_verdicts'),
    "review_verdicts": ("guji_manager.review.verdict_view", 'review_verdicts'),
    "verdicts_by_question": ("guji_manager.review.verdict_view", 'verdicts_by_question'),
    # steps._warpmap
    "ColumnMapper": ("steps._warpmap", 'ColumnMapper'),
    # steps.align_ref
    "align_ref_summary": ("steps.align_ref", 'align_ref_summary'),
    "book_corpus": ("steps.align_ref", 'book_corpus'),
    # steps.glyph_match
    "GlyphMatchParams": ("steps.glyph_match", 'GlyphMatchParams'),
    "db_fingerprint": ("steps.glyph_match", 'db_fingerprint'),
    "glyph_match_summary": ("steps.glyph_match", 'glyph_match_summary'),
    # utils.binarized
    "binarize_page": ("utils.binarized", 'binarize_page'),
    "binarized_or_none": ("utils.binarized", 'binarized_or_none'),
    # seg.profile、books.siku_zongmu.column（原 utils.column_projection）
    "column_profile": ("seg.profile", 'column_profile'),
    "column_row_profile": ("seg.profile", 'column_row_profile'),
    "column_text_band": ("seg.profile", 'column_text_band'),
    "denoise_column": ("seg.profile", 'denoise_column'),
    "strip_column_rules": ("books.siku_zongmu.column", 'strip_column_rules'),
    # books.siku_zongmu.column_triage
    "BLOCKING": ("books.siku_zongmu.column_triage", 'BLOCKING'),
    "REVIEW": ("books.siku_zongmu.column_triage", 'REVIEW'),
    "triage_column": ("books.siku_zongmu.column_triage", 'triage_column'),
    # utils.image_io
    "imread": ("utils.image_io", 'imread'),
    # utils.jiazhu_order
    "sort_by_reading": ("utils.jiazhu_order", 'sort_by_reading'),
    # utils.preclean
    "effective_raw_path": ("utils.preclean", 'effective_raw_path'),
    "precleaned_path": ("utils.preclean", 'precleaned_path'),
    # variant_ledger
    "DEFAULT_EDITION": ("variant_ledger", 'DEFAULT_EDITION'),
    "ledger_path": ("variant_ledger", 'ledger_path'),
}

__all__ = sorted(_EXPORTS) + ["register_all"]


def __getattr__(name: str) -> Any:
    try:
        mod, attr = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"open_guji_cv.console_api 没有导出 {name!r}"
                             f"（控制台只许用门面里登记过的名字，见模块头）") from None
    m = _resolve_module(mod)
    return m if attr is None else getattr(m, attr)


def _resolve_module(mod: str):
    """`guji_manager.` 开头的是已搬去 guji-manager 的（拆分 P2 第四批起），其余是 cv 内模块。"""
    if mod.startswith("guji_manager."):
        try:
            return importlib.import_module(mod)
        except ModuleNotFoundError as e:
            if e.name and e.name.startswith("guji_manager"):
                raise ImportError(f"{mod} 已搬去 guji-manager，本机没装或版本太旧（装法见 cv scripts/ensure_manager.sh）") from e
            raise
    return importlib.import_module(f"{_PKG}.{mod}")


def __dir__() -> list[str]:
    return __all__


def register_all() -> None:
    """import 即注册：全部 Step 与产物种类（`steps`）、事件路由与消费者（`feedback`）。"""
    importlib.import_module(f"{_PKG}.steps")
    importlib.import_module(f"{_PKG}.feedback")
    try:                                     # Step8（落库反馈）已搬去 guji-manager（拆分 P2 第四批）
        importlib.import_module("guji_manager.feedback")
    except ImportError:
        pass
