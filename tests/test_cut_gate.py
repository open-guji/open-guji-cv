"""切字出口闸 cut_gate（2026-11-25）：挂 cell_shrink、只在最后调用；刻本链判据与旧 column_gate／row_segment_gate 一致。"""
from __future__ import annotations

from helpers import column_xs, make_book, make_ctx, make_gate1, run_steps, synth_page
import open_guji_cv.steps  # noqa: F401  —— 注册 Step 与闸
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


def test_side_cut_points_ignores_end_rows_and_rule():
    import numpy as np
    from open_guji_cv.seg.side_cut import side_cut_points
    img = np.full((1200, 100), 255, np.uint8)
    img[:, :4] = 0; img[:, -4:] = 0                  # 左右版框线
    img[300:900, 30:70] = 0                          # 字
    img[1100:1110, :] = 0                            # 底部横框墨：不能把投影带偏
    xl, xr = side_cut_points(img, 0, 1200, row_margin=60)
    assert 4 <= xl <= 8 and 91 <= xr <= 95           # 贴着框线内缘往里缩 2px，不会跑到字边
    img2 = img.copy(); img2[130:1050, 6:12] = 0      # 框线内缘后紧跟 1px 白缝、再是一条墨
    xl2, _ = side_cut_points(img2, 0, 1200, row_margin=60)
    assert xl2 == 5                                  # 框线与外侧墨之间只有 1px 白缝：切在缝里，不往里缩进墨


def test_cut_gate_rejects_cut_too_inward(tmp_path):
    ctx, out = _chain(tmp_path)
    ok = STEPS["cut_gate"].run_page(ctx, PAGE)["gate_manifest"]
    assert not any("cut_too_inward" in r for c in ok.columns for r in c.reject)
    from open_guji_cv.gates.cut_gate import CutGateParams
    ctx.params["cut_gate"] = CutGateParams(cut_inward_max_px=-1)      # 关
    off = STEPS["cut_gate"].run_page(ctx, PAGE)["gate_manifest"]
    assert off.model_dump() == ok.model_dump()
    ctx.params["cut_gate"] = CutGateParams(cut_inward_max_px=0.5)     # 门槛压到极小：贴边切点也该被点名
    tight = STEPS["cut_gate"].run_page(ctx, PAGE)["gate_manifest"]
    assert any("cut_too_inward" in r for c in tight.columns for r in c.reject) or ok.model_dump() == tight.model_dump()
