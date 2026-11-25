"""切字出口闸 cut_gate（2026-11-25）：挂 cell_shrink、只在最后调用；刻本链判据与旧 column_gate／row_segment_gate 一致。"""
from __future__ import annotations

from helpers import column_xs, make_book, make_ctx, make_gate1, run_steps, synth_page
from open_guji_cv.core.pipeline import load_pipeline
from open_guji_cv.core.step import STEPS

PAGE = 2


def _chain(tmp_path, xs=None):
    gray, borders = synth_page(xs=xs or column_xs(n_cols=9))
    book = make_book(expected_cols=borders.expected_cols)
    ctx = make_ctx(tmp_path, book, raw={PAGE: gray})
    ctx.store.write(book.id, "border_detect", f"p{PAGE:04d}", {"borders": borders})
    ctx.store.write(book.id, "border_detect_gate", f"p{PAGE:04d}", {"border_detect_gate_manifest": make_gate1(
        PAGE, n_cols=borders.expected_cols, expected_cols=book.expected_cols)})
    return ctx, run_steps(ctx, PAGE, ["column_warp", "column_band", "column_end", "column_geometry",
                                      "column_gate", "row_segment", "cell_shrink"])


def test_cut_gate_matches_legacy_gates(tmp_path):
    ctx, out = _chain(tmp_path)
    res = STEPS["cut_gate"].run_page(ctx, PAGE)
    assert res["gate_manifest"].model_dump() == out["gate_manifest"].model_dump()
    legacy = STEPS["row_segment_gate"].run_page(ctx, PAGE)["row_segment_gate_manifest"]
    assert res["row_segment_gate_manifest"].model_dump() == legacy.model_dump()


def test_gate_applies_only_to_chain_that_has_its_inputs():
    keben, modern = load_pipeline("keben_body_v2"), load_pipeline("modern_body")
    assert keben.gate_of("cell_shrink").id == "cut_gate"
    assert modern.gate_of("cell_shrink") is None            # 现代链没有 column_geometry，不跑 cut_gate
    assert modern.gate_of("column_crop").id == "column_gate"
    assert keben.gate_of("column_end") is None              # 出口闸不再挡 2a–2c
    assert keben.producer_of("gate_manifest").spec.id == "cut_gate"
